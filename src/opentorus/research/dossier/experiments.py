"""Reproducible experiment manifests for a dossier (Milestone M1, Phase 7).

Every experiment is a directory ``experiments/EXP-XXXX/`` with a manifest that
records exactly how to reproduce it: the command, working directory, Python
version, a dependencies hash, the git commit, and the random seed. An experiment
may *support* or *contradict* a claim; it may never *verify* one.
"""

from __future__ import annotations

import hashlib
import os
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


# The agent's exp_new/exp_run tools use the WORKSPACE-level experiment store
# (``.opentorus/experiments/EXP-*``, statuses created/running/completed/failed),
# not this dossier-level one. Reports, the status gate, PDF export, and the
# experiment-citation check must see both, or completed agent runs render as
# "(none)" and EXPERIMENTAL_ONLY can never derive from agent work.
_WS_STATUS_MAP = {
    "created": "planned",
    "running": "running",
    "completed": "succeeded",
    "failed": "failed",
}


def _workspace_experiment_record(ot_dir: Path, exp) -> ExperimentRecord:  # noqa: ANN001
    """Adapt a workspace-level experiment for dossier rendering (record-only view)."""
    summary = getattr(exp, "result_summary", "") or ""
    if not summary:
        # Records written before result_summary existed: derive from the manifest.
        manifest = ot_dir / exp.path / "results" / "manifest.yaml"
        if manifest.is_file():
            data = yaml.safe_load(manifest.read_text("utf-8")) or {}
            code = data.get("exit_code")
            summary = f"ran (exit {code}); results under .opentorus/{exp.path}/results/"
    return ExperimentRecord(
        experiment_id=exp.id,
        problem_id=exp.problem_id or "",
        title=exp.title,
        command=exp.command or "",
        status=_WS_STATUS_MAP.get(exp.status, "planned"),  # type: ignore[arg-type]
        result_summary=summary,
        created_at=exp.created_at,
    )


def _attributed_workspace_experiments(ot_dir: Path, problem_id: str) -> list:
    """Workspace experiments belonging to this problem (same rule as `problem show`):
    tagged with the problem id, plus untagged ones when the workspace has a single
    dossier (legacy records can only belong to it)."""
    from opentorus.research.experiments import list_experiments as ws_list

    pid = problem_id.strip().upper()
    records = ws_list(ot_dir)
    single_dossier = len(store.list_dossiers(ot_dir)) == 1
    return [
        e
        for e in records
        if (e.problem_id or "").strip().upper() == pid or (e.problem_id is None and single_dossier)
    ]


def list_problem_experiments(ot_dir: Path, problem_id: str) -> list[ExperimentRecord]:
    """Dossier experiments plus the agent's workspace experiments for this problem.

    On an id collision across the two stores the dossier record wins (harvested
    records continue the dossier numbering, so collisions are rare and transient).
    """
    records = list_experiments(ot_dir, problem_id)
    seen = {getattr(r, "experiment_id", None) for r in records}
    for exp in _attributed_workspace_experiments(ot_dir, problem_id):
        if exp.id in seen:
            continue
        records.append(_workspace_experiment_record(ot_dir, exp))
    return records


def get_problem_experiment(ot_dir: Path, problem_id: str, exp_id: str) -> ExperimentRecord | None:
    """Look up an EXP-* in the dossier store, then among attributed workspace runs."""
    rec = get_experiment(ot_dir, problem_id, exp_id)
    if rec is not None:
        return rec
    wanted = exp_id.strip().upper()
    for exp in _attributed_workspace_experiments(ot_dir, problem_id):
        if exp.id.strip().upper() == wanted:
            return _workspace_experiment_record(ot_dir, exp)
    return None


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
        f"#!/usr/bin/env bash\nset -euo pipefail\n{seed_line}{command}\n",
        encoding="utf-8",
        # LF always: a CRLF run.sh (Windows text-mode default) breaks bash
        # ("set -euo pipefail\r"), and the script's bytes should not depend on
        # which host scaffolded the experiment.
        newline="\n",
    )
    (edir / "run.sh").chmod(0o755)
    (edir / "result.md").write_text(
        f"# {exp_id} — {title}\n\n_Status: planned. Run `opentorus replay {problem_id}`._\n",
        encoding="utf-8",
    )
    _save_manifest(ot_dir, exp)
    return exp


def _bash_executable() -> str:
    """Locate the bash that runs ``run.sh``.

    On Windows a bare ``bash`` often resolves to the System32 WSL shim, which
    exits nonzero (with its message on stdout, in UTF-16) when no distribution
    is installed — so prefer Git Bash explicitly.
    """
    if os.name == "nt":
        for env_var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            base = os.environ.get(env_var)
            if base:
                candidate = Path(base) / "Git" / "bin" / "bash.exe"
                if candidate.is_file():
                    return str(candidate)
    return "bash"


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
            [_bash_executable(), str(edir / "run.sh")],
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
    except FileNotFoundError as exc:  # no bash on this host (e.g. bare Windows)
        (edir / "stderr.log").write_text(f"{exc}\n", encoding="utf-8")
        exp.status = "failed"
        exp.result_summary = "bash is required to run experiments (on Windows, install Git Bash)."
        _save_manifest(ot_dir, exp)
        return exp

    (edir / "stdout.log").write_text(proc.stdout, encoding="utf-8")
    (edir / "stderr.log").write_text(proc.stderr, encoding="utf-8")
    exp.status = "succeeded" if proc.returncode == 0 else "failed"
    # Reproducibility: hash stdout. The first successful run sets the baseline; a
    # later run diffs against it and reports drift rather than silently overwriting.
    repro_note = ""
    if proc.returncode == 0:
        new_sha = hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest()
        if exp.stdout_sha256 is None:
            exp.stdout_sha256 = new_sha
        elif new_sha != exp.stdout_sha256:
            repro_note = " NON-REPRODUCIBLE: stdout differs from the recorded baseline."
        else:
            repro_note = " reproducible (stdout matches baseline)."
    exp.result_summary = (
        f"exit={proc.returncode}; stdout {len(proc.stdout)} chars, "
        f"stderr {len(proc.stderr)} chars.{repro_note}"
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
