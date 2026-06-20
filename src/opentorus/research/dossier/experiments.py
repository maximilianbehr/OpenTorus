"""Reproducible experiment manifests for a dossier (Milestone M1, Phase 7).

Every experiment is a directory ``experiments/EXP-XXXX/`` with a manifest that
records exactly how to reproduce it: the command, working directory, Python
version, a dependencies hash, the git commit, and the random seed. An experiment
may *support* or *contradict* a claim; it may never *verify* one.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from importlib import metadata
from pathlib import Path

import yaml

from opentorus.errors import OpenTorusError
from opentorus.jsonl import next_sequential_id
from opentorus.research.dossier import store
from opentorus.research.dossier.models import ExperimentRecord, utcnow


def experiments_dir(ot_dir: Path, problem_id: str) -> Path:
    return store.dossier_dir(ot_dir, problem_id) / "experiments"


def experiment_dir(ot_dir: Path, problem_id: str, exp_id: str) -> Path:
    return experiments_dir(ot_dir, problem_id) / exp_id


def _manifest_path(ot_dir: Path, problem_id: str, exp_id: str) -> Path:
    return experiment_dir(ot_dir, problem_id, exp_id) / "manifest.yaml"


def list_experiments(ot_dir: Path, problem_id: str) -> list[ExperimentRecord]:
    root = experiments_dir(ot_dir, problem_id)
    if not root.is_dir():
        return []
    out: list[ExperimentRecord] = []
    for child in sorted(root.iterdir()):
        manifest = child / "manifest.yaml"
        if manifest.is_file():
            out.append(ExperimentRecord.model_validate(yaml.safe_load(manifest.read_text("utf-8"))))
    return out


def get_experiment(ot_dir: Path, problem_id: str, exp_id: str) -> ExperimentRecord | None:
    manifest = _manifest_path(ot_dir, problem_id, exp_id)
    if not manifest.is_file():
        return None
    return ExperimentRecord.model_validate(yaml.safe_load(manifest.read_text("utf-8")))


def _save_manifest(ot_dir: Path, exp: ExperimentRecord) -> None:
    path = _manifest_path(ot_dir, exp.problem_id, exp.experiment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(exp.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _git_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = out.stdout.strip()
    return commit or None


def _dependencies_hash() -> str:
    try:
        dists = sorted(f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions())
    except Exception:  # noqa: BLE001 - environment introspection is best-effort
        return ""
    digest = hashlib.sha256("\n".join(dists).encode("utf-8")).hexdigest()
    return digest[:16]


def create_experiment(
    ot_dir: Path,
    problem_id: str,
    *,
    title: str,
    command: str,
    working_directory: str = ".",
    random_seed: int | None = None,
    input_artifacts: list[str] | None = None,
    claim_links: list[str] | None = None,
) -> ExperimentRecord:
    """Scaffold a reproducible experiment directory and manifest."""
    store.require_dossier(ot_dir, problem_id)
    if not command.strip():
        raise OpenTorusError("An experiment needs a command to be reproducible.")
    exp_id = next_sequential_id("EXP", len(list_experiments(ot_dir, problem_id)))
    exp = ExperimentRecord(
        experiment_id=exp_id,
        problem_id=problem_id,
        title=title,
        command=command,
        working_directory=working_directory,
        python_version=platform.python_version(),
        dependencies_hash=_dependencies_hash(),
        git_commit=_git_commit(ot_dir.parent),
        random_seed=random_seed,
        input_artifacts=input_artifacts or [],
        claim_links=claim_links or [],
        created_at=utcnow(),
        status="planned",
    )
    edir = experiment_dir(ot_dir, problem_id, exp_id)
    (edir / "artifacts").mkdir(parents=True, exist_ok=True)
    (edir / "artifacts" / ".gitkeep").touch()
    seed_line = f"export PYTHONHASHSEED={random_seed}\n" if random_seed is not None else ""
    (edir / "run.sh").write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\n{seed_line}{command}\n", encoding="utf-8"
    )
    (edir / "run.sh").chmod(0o755)
    (edir / "result.md").write_text(
        f"# {exp_id} — {title}\n\n_Status: planned. Run `opentorus replay {problem_id}`._\n",
        encoding="utf-8",
    )
    _save_manifest(ot_dir, exp)
    return exp


def run_experiment(
    ot_dir: Path, problem_id: str, exp_id: str, *, timeout: int = 300
) -> ExperimentRecord:
    """Execute an experiment's command, capture logs, and record the outcome.

    Sets status to ``succeeded``/``failed`` from the exit code. The result is
    evidence, not proof; reports must cite the EXP-* id, never 'we tested it'.
    """
    exp = get_experiment(ot_dir, problem_id, exp_id)
    if exp is None:
        raise OpenTorusError(f"No experiment '{exp_id}' in dossier '{problem_id}'.")
    edir = experiment_dir(ot_dir, problem_id, exp_id)
    cwd = (ot_dir.parent / exp.working_directory).resolve()

    exp.status = "running"
    _save_manifest(ot_dir, exp)
    try:
        proc = subprocess.run(
            ["bash", str(edir / "run.sh")],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        (edir / "stderr.log").write_text(f"Timed out after {timeout}s.\n", encoding="utf-8")
        exp.status = "inconclusive"
        exp.result_summary = f"Timed out after {timeout}s."
        _save_manifest(ot_dir, exp)
        return exp

    (edir / "stdout.log").write_text(proc.stdout, encoding="utf-8")
    (edir / "stderr.log").write_text(proc.stderr, encoding="utf-8")
    exp.status = "succeeded" if proc.returncode == 0 else "failed"
    exp.result_summary = (
        f"exit={proc.returncode}; stdout {len(proc.stdout)} chars, stderr {len(proc.stderr)} chars."
    )
    (edir / "result.md").write_text(
        f"# {exp_id} — {exp.title}\n\n"
        f"_Status: {exp.status} (evidence, not proof)._\n\n"
        f"- exit code: {proc.returncode}\n"
        f"- command: `{exp.command}`\n"
        f"- random seed: {exp.random_seed}\n",
        encoding="utf-8",
    )
    _save_manifest(ot_dir, exp)
    return exp
