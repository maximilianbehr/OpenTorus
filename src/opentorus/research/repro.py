"""Reproducibility replay for experiments.

Where session replay (M19) reconstructs *what happened* for audit, this module
attempts *faithful re-execution*: it re-runs a recorded experiment and diffs the
fresh outcome against the recorded manifest (M21). It never overwrites the
recorded results -- the original run stays the source of truth. Divergences are
reported honestly as evidence; a non-reproducible run is a finding, not a
failure to hide.
"""

from __future__ import annotations

import difflib
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.research.experiments import (
    ResultManifest,
    _extract_seed,
    get_experiment,
)
from opentorus.tools.shell import run_shell


class ReplayReport(BaseModel):
    experiment_id: str
    reproducible: bool
    recorded_exit_code: int
    replay_exit_code: int
    recorded_seed: int | None = None
    replay_seed: int | None = None
    stdout_matches: bool = False
    stdout_diff: str = ""
    environment_changes: dict = Field(default_factory=dict)
    divergences: list[str] = Field(default_factory=list)
    replayed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _load_manifest(exp_dir: Path) -> ResultManifest:
    path = exp_dir / "results" / "manifest.yaml"
    if not path.is_file():
        raise OpenTorusError(
            "No result manifest found. Run the experiment first so a baseline exists."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ResultManifest.model_validate(data)


def _current_environment() -> dict:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def replay_experiment(ot_dir: Path, exp_id: str, timeout: int = 120) -> ReplayReport:
    """Re-run a recorded experiment and diff the outcome against its manifest."""
    experiment = get_experiment(ot_dir, exp_id)
    if experiment is None:
        raise OpenTorusError(f"No experiment with id '{exp_id}'.")

    exp_dir = ot_dir / experiment.path
    manifest = _load_manifest(exp_dir)
    recorded_stdout = (exp_dir / "results" / "stdout.txt").read_text(
        encoding="utf-8", errors="replace"
    )

    # Re-run without touching the recorded results directory.
    result = run_shell(f"{sys.executable} run.py", cwd=exp_dir, timeout=timeout)
    replay_seed = _extract_seed(result.stdout)

    divergences: list[str] = []
    if result.exit_code != manifest.exit_code:
        divergences.append(
            f"exit code changed: recorded {manifest.exit_code}, replay {result.exit_code}"
        )

    stdout_matches = result.stdout == recorded_stdout
    stdout_diff = ""
    if not stdout_matches:
        stdout_diff = "".join(
            difflib.unified_diff(
                recorded_stdout.splitlines(keepends=True),
                result.stdout.splitlines(keepends=True),
                fromfile="recorded stdout",
                tofile="replay stdout",
            )
        )
        divergences.append("stdout differs from the recorded run")

    if manifest.random_seed != replay_seed:
        divergences.append(f"seed changed: recorded {manifest.random_seed}, replay {replay_seed}")

    environment_changes: dict = {}
    current_env = _current_environment()
    for key, current in current_env.items():
        recorded = manifest.environment.get(key)
        if recorded is not None and recorded != current:
            environment_changes[key] = {"recorded": recorded, "current": current}
    if environment_changes:
        divergences.append(
            "environment differs from the recorded run (results may not be comparable)"
        )

    report = ReplayReport(
        experiment_id=exp_id,
        reproducible=not divergences,
        recorded_exit_code=manifest.exit_code,
        replay_exit_code=result.exit_code,
        recorded_seed=manifest.random_seed,
        replay_seed=replay_seed,
        stdout_matches=stdout_matches,
        stdout_diff=stdout_diff,
        environment_changes=environment_changes,
        divergences=divergences,
    )
    _write_report(exp_dir, report)
    return report


def _write_report(exp_dir: Path, report: ReplayReport) -> Path:
    replays = exp_dir / "results" / "replays"
    replays.mkdir(parents=True, exist_ok=True)
    out = replays / f"{report.replayed_at.strftime('%Y%m%dT%H%M%S')}.yaml"
    out.write_text(
        yaml.safe_dump(report.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    return out
