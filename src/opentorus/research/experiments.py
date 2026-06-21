"""Reproducible experiment folders.

Each experiment is a self-contained directory under ``.opentorus/experiments/``
with a ``config.yaml`` (metadata), a stdlib-only ``run.py`` template, a
``results/`` directory, and a ``summary.md``. Running an experiment captures
stdout/stderr and updates status. Results are always framed as evidence, never as
final validation.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from opentorus.actions import log_action
from opentorus.config import CONFIG_FILENAME, Config, default_config, load_config
from opentorus.errors import OpenTorusError
from opentorus.jsonl import next_sequential_id
from opentorus.tools.shell import ShellResult, run_shell

ExperimentStatus = Literal["created", "running", "completed", "failed"]
RunFrom = Literal["experiment", "workspace"]

EVIDENCE_NOTE = "This experiment may provide evidence, not final validation."

_RUN_TEMPLATE = '''\
"""Experiment entry point.

Safe, stdlib-only template: deterministic via a fixed seed, prints a JSON result
to stdout. Replace the body with your actual experiment.
"""

import json
import random

SEED = 42


def main() -> None:
    random.seed(SEED)
    result = {"seed": SEED, "metric": round(random.random(), 6), "samples": 10}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
'''


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _assert_command_allowed(command: str | None, environment: str | None) -> None:
    """Enforce the non-bypassable command guarantees for experiment execution.

    ``exp_run`` runs a stored command outside the agent loop's permission gate, so
    the hard guarantees that hold for ``run_shell`` (always-blocked dangerous
    commands; no host package installs) are enforced here at the single execution
    choke point. Dangerous commands are blocked regardless of environment; host
    package installs are blocked only when running on the host (no container).
    """
    from opentorus.permissions.policy import is_dangerous_command, is_package_install_command

    if not command:
        return
    if is_dangerous_command(command):
        raise OpenTorusError(
            f"Experiment command matches a dangerous pattern and is always blocked: {command!r}."
        )
    if environment is None and is_package_install_command(command):
        raise OpenTorusError(
            "Experiment command installs packages on the host, which is blocked. "
            "Build a container image (opentorus env prepare <env> --file <Dockerfile>) "
            "and create the experiment with environment=<env> so dependencies are baked in."
        )


class DatasetRef(BaseModel):
    """A dataset consumed by an experiment, pinned by its content hash (M71)."""

    dataset_id: str
    sha256: str | None = None


class Experiment(BaseModel):
    id: str
    title: str
    path: str
    status: ExperimentStatus = "created"
    command: str | None = None
    run_from: RunFrom = "experiment"
    environment: str | None = None
    # Problem dossier this experiment was created under (attribution). None for
    # legacy records or experiments created outside any active problem.
    problem_id: str | None = None
    # Datasets consumed as inputs (provenance for the result manifest, M71).
    datasets: list[DatasetRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


def experiments_dir(ot_dir: Path) -> Path:
    return ot_dir / "experiments"


def _meta_path(exp_dir: Path) -> Path:
    return exp_dir / "config.yaml"


def _save_meta(ot_dir: Path, experiment: Experiment) -> None:
    path = _meta_path(ot_dir / experiment.path)
    path.write_text(yaml.safe_dump(experiment.model_dump(mode="json"), sort_keys=False), "utf-8")


def _write_summary(ot_dir: Path, experiment: Experiment) -> None:
    summary = (
        f"# {experiment.id} — {experiment.title}\n\n"
        f"- Status: {experiment.status}\n"
        f"- Command: {experiment.command}\n\n"
        f"> {EVIDENCE_NOTE}\n"
    )
    (ot_dir / experiment.path / "summary.md").write_text(summary, encoding="utf-8")


def list_experiments(ot_dir: Path, *, problem_id: str | None = None) -> list[Experiment]:
    base = experiments_dir(ot_dir)
    if not base.is_dir():
        return []
    experiments: list[Experiment] = []
    for child in sorted(base.iterdir()):
        meta = _meta_path(child)
        if child.is_dir() and meta.is_file():
            data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
            experiments.append(Experiment.model_validate(data))
    if problem_id is not None:
        return [e for e in experiments if e.problem_id == problem_id]
    return experiments


def get_experiment(ot_dir: Path, exp_id: str) -> Experiment | None:
    for experiment in list_experiments(ot_dir):
        if experiment.id == exp_id:
            return experiment
    return None


def attach_dataset(
    ot_dir: Path, exp_id: str, *, dataset_id: str, sha256: str | None = None
) -> Experiment:
    """Record a dataset as an input to an experiment (manifest provenance, M71)."""
    experiment = get_experiment(ot_dir, exp_id)
    if experiment is None:
        raise OpenTorusError(f"No experiment with id '{exp_id}'.")
    if any(ref.dataset_id == dataset_id for ref in experiment.datasets):
        return experiment
    experiment.datasets.append(DatasetRef(dataset_id=dataset_id, sha256=sha256))
    experiment.updated_at = _utcnow()
    _save_meta(ot_dir, experiment)
    return experiment


def find_experiment_by_command(ot_dir: Path, command: str) -> Experiment | None:
    """Return the newest experiment whose command matches ``command`` (whitespace-normalized)."""
    normalized = " ".join(command.split())
    if not normalized:
        return None
    for experiment in reversed(list_experiments(ot_dir)):
        if experiment.command and " ".join(experiment.command.split()) == normalized:
            return experiment
    return None


def new_experiment(
    ot_dir: Path,
    title: str,
    template: str = "default",
    environment: str | None = None,
    run_body: str | None = None,
    command: str | None = None,
    run_from: RunFrom = "experiment",
    problem_id: str | None = None,
) -> Experiment:
    base = experiments_dir(ot_dir)
    base.mkdir(parents=True, exist_ok=True)
    existing = list_experiments(ot_dir)
    exp_id = next_sequential_id("EXP", len(existing))
    rel = f"experiments/{exp_id}"
    exp_dir = ot_dir / rel
    (exp_dir / "results").mkdir(parents=True, exist_ok=True)

    # An explicit ``run_body`` (e.g. a parameter-sweep cell) wins over templates.
    if run_body is None:
        if template == "default":
            run_body = _RUN_TEMPLATE
        else:
            from opentorus.research.math_experiments import MATH_TEMPLATES

            if template not in MATH_TEMPLATES:
                valid = ", ".join(["default", *MATH_TEMPLATES])
                raise OpenTorusError(f"Unknown experiment template '{template}'. Valid: {valid}")
            run_body = MATH_TEMPLATES[template]
    (exp_dir / "run.py").write_text(run_body, encoding="utf-8")

    # A named environment determines the in-container command (e.g. ``julia
    # run.jl``); validate it eagerly so an unknown name fails at creation.
    resolved_command = command or "python run.py"
    if environment is not None and command is None:
        from opentorus.execution.environments import resolve_environment

        resolved_command = resolve_environment(ot_dir, environment).default_command

    # Refuse to even store a command that could never be run safely, so the
    # model gets immediate feedback at creation rather than at exp_run time.
    _assert_command_allowed(resolved_command, environment)

    resolved_run_from = run_from
    if command is not None and run_from == "experiment" and command != "python run.py":
        # Commands like ``python scripts/foo.py`` must run from the workspace root.
        resolved_run_from = "workspace"

    experiment = Experiment(
        id=exp_id,
        title=title,
        path=rel,
        status="created",
        command=resolved_command,
        run_from=resolved_run_from,
        environment=environment,
        problem_id=problem_id,
    )
    _save_meta(ot_dir, experiment)
    _write_summary(ot_dir, experiment)
    return experiment


def _read_text(path: Path, limit: int = 4000) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def summarize_experiment(ot_dir: Path, exp_id: str, provider=None) -> Experiment:
    """Generate a rich ``summary.md`` from the experiment's config and results.

    The summary is deterministic. A ``provider`` may be supplied for future
    LLM-based narration but is not required; results are always framed as
    evidence, never as final validation.
    """
    experiment = get_experiment(ot_dir, exp_id)
    if experiment is None:
        raise OpenTorusError(f"No experiment with id '{exp_id}'.")

    exp_dir = ot_dir / experiment.path
    results_dir = exp_dir / "results"
    stdout = _read_text(results_dir / "stdout.txt")
    stderr = _read_text(results_dir / "stderr.txt")

    result_files = []
    if results_dir.is_dir():
        result_files = sorted(p.name for p in results_dir.iterdir() if p.is_file())

    if experiment.status == "failed":
        observed = "The run exited with a non-zero status; see stderr below. Validation failed."
    elif experiment.status == "completed":
        observed = "The run completed. stdout is reproduced below as observed output."
    else:
        observed = "The experiment has not been run yet, so there is no observed behavior."

    files_body = "\n".join(f"- `results/{name}`" for name in result_files) or "_None yet._"
    manifest_exists = (results_dir / "manifest.yaml").is_file()
    parts = [
        f"# {experiment.id} — {experiment.title}",
        "",
        "## Parameters",
        "",
        f"- Status: {experiment.status}",
        f"- Command: {experiment.command}",
        f"- Last updated: {experiment.updated_at.isoformat()}",
        "",
        "## Result files",
        "",
        files_body,
        "",
        "## Reproducibility",
        "",
        (
            "See `results/manifest.yaml` for the command, exit code, environment, "
            "git commit, and random seed of this run."
            if manifest_exists
            else "_No manifest yet — run the experiment to capture one._"
        ),
        "",
        "## Observed behavior",
        "",
        observed,
        "",
        "### stdout",
        "",
        "```",
        stdout.strip() or "(empty)",
        "```",
        "",
        "### stderr",
        "",
        "```",
        stderr.strip() or "(empty)",
        "```",
        "",
        "## Limitations",
        "",
        "- Single run; no statistical replication or significance testing.",
        "- Conclusions are not drawn here — only observations are reported.",
        "",
        "## Evidence note",
        "",
        f"> {EVIDENCE_NOTE}",
        "",
    ]
    (exp_dir / "summary.md").write_text("\n".join(parts), encoding="utf-8")
    return experiment


class ResultManifest(BaseModel):
    experiment_id: str
    command: str
    start_time: datetime
    end_time: datetime
    exit_code: int
    status: ExperimentStatus
    stdout_path: str
    stderr_path: str
    result_files: list[str] = Field(default_factory=list)
    environment: dict = Field(default_factory=dict)
    git_commit: str | None = None
    dirty_git_state: bool | None = None
    random_seed: int | None = None
    # Execution provenance (Phase 18): which backend/image actually ran this.
    backend: str | None = None
    backend_version: str | None = None
    tool_environment: str | None = None
    image_ref: str | None = None
    tool_versions: dict = Field(default_factory=dict)
    # Scale & HPC reproducibility (Phase 21): pinned digest, SIF cache, result cache.
    image_digest: str | None = None
    sif_cache: str | None = None
    cache_hit: bool = False
    cache_key: str | None = None
    # Dataset inputs consumed by this run, pinned by content hash (Phase 23, M71).
    datasets: list[dict] = Field(default_factory=list)


def _git_commit_dirty(root: Path) -> tuple[str | None, bool | None]:
    def _git(args: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return None

    commit = _git(["rev-parse", "HEAD"])
    status = _git(["status", "--porcelain"])
    return (
        commit.stdout.strip() if commit and commit.returncode == 0 else None,
        bool(status.stdout.strip()) if status and status.returncode == 0 else None,
    )


def _capture_environment(root: Path, config: Config, exp_dir: Path) -> dict:
    """Capture environment metadata, gated by ``config.environment`` flags."""
    environment: dict = {}
    if config.environment.capture_os_info:
        environment["python_version"] = platform.python_version()
        environment["platform"] = platform.platform()
        environment["working_directory"] = str(root)
    if config.environment.capture_pip_freeze:
        result = run_shell(f"{sys.executable} -m pip freeze", cwd=root, timeout=120)
        if result.exit_code == 0:
            (exp_dir / "results" / "environment-pip-freeze.txt").write_text(
                result.stdout, encoding="utf-8"
            )
            environment["pip_freeze_path"] = "results/environment-pip-freeze.txt"
    return environment


def _extract_seed(stdout: str) -> int | None:
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        seed = data.get("seed")
        if isinstance(seed, int):
            return seed
    return None


def _load_config(ot_dir: Path) -> Config:
    config_path = ot_dir / CONFIG_FILENAME
    return load_config(config_path) if config_path.is_file() else default_config()


class ExecProvenance(BaseModel):
    """Which backend/image actually executed a run (recorded in the manifest)."""

    backend: str
    backend_version: str | None = None
    tool_environment: str | None = None
    image_ref: str | None = None
    tool_versions: dict = Field(default_factory=dict)
    image_digest: str | None = None
    sif_cache: str | None = None


def _run_via_backend(
    ot_dir: Path,
    config: Config,
    experiment: Experiment,
    exp_dir: Path,
    timeout: int,
) -> tuple[ShellResult, ExecProvenance]:
    """Run an experiment through the configured execution backend.

    With no declared ``environment`` this resolves to the host (``local``) and is
    behaviour-compatible with the original ``run_shell`` call. A named environment
    (M56) supplies a digest-pinned image and the in-container command; the chosen
    backend and image are recorded as provenance for reproducibility.
    """
    from opentorus.execution import ExecutionRequest, RunLimits, select_backend

    root = ot_dir.parent
    image: str | None = None
    env_name = experiment.environment
    default_command = experiment.command or f"{sys.executable} run.py"
    if env_name is not None:
        from opentorus.execution.environments import resolve_environment

        env = resolve_environment(ot_dir, env_name)
        image = env.image
        in_container_command = experiment.command or env.default_command
        if not image:
            msg = (
                f"Environment '{env_name}' has no container image. "
                f"Run: opentorus env prepare {env_name} --file path/to/Dockerfile"
            )
            result = ShellResult(
                command=in_container_command,
                stdout="",
                stderr=msg,
                exit_code=127,
            )
            provenance = ExecProvenance(
                backend="unavailable",
                tool_environment=env_name,
                image_ref=None,
            )
            return result, provenance
    else:
        in_container_command = default_command
    workdir = root if experiment.run_from == "workspace" else exp_dir

    backend = select_backend(config, needs_image=image is not None)
    # If we asked for an image but fell back to the host, do not run on the host
    # with the wrong toolchain — report honestly instead of faking the result.
    if image is not None and not getattr(backend, "requires_image", False):
        result = ShellResult(
            command=in_container_command,
            stdout="",
            stderr=(
                f"Environment '{env_name}' needs a container runtime, but none "
                "is available. Install Docker/Podman/Apptainer or set "
                "config.execution.backend. Run not executed."
            ),
            exit_code=127,
        )
        provenance = ExecProvenance(
            backend="unavailable", tool_environment=env_name, image_ref=image
        )
        return result, provenance

    request = ExecutionRequest(
        command=in_container_command,
        workdir=workdir,
        image=image,
        network=config.execution.network,
        limits=RunLimits(
            timeout=timeout,
            memory=config.execution.memory_limit,
            cpus=config.execution.cpu_limit,
        ),
    )
    result = backend.run(request)
    from opentorus.execution.pinning import image_digest as _digest
    from opentorus.execution.pinning import sif_cache_path

    digest = _digest(image)
    sif_cache = str(sif_cache_path(digest)) if (digest and backend.name == "apptainer") else None
    provenance = ExecProvenance(
        backend=backend.name,
        backend_version=backend.version(),
        tool_environment=env_name,
        image_ref=image if backend.requires_image else None,
        image_digest=digest if backend.requires_image else None,
        sif_cache=sif_cache,
    )
    return result, provenance


def _resolve_image_ref(ot_dir: Path, experiment: Experiment) -> str | None:
    if experiment.environment is None:
        return None
    from opentorus.execution.environments import resolve_environment

    return resolve_environment(ot_dir, experiment.environment).image


def _cache_key_for(ot_dir: Path, experiment: Experiment, exp_dir: Path) -> str:
    from opentorus.execution.cache import cache_key

    run_py = exp_dir / "run.py"
    run_source = run_py.read_text(encoding="utf-8") if run_py.is_file() else ""
    # Attached datasets are inputs: fold their (id, sha256) into the key so a run with
    # the same script but different data does not restore the wrong cached result.
    datasets = sorted((d.dataset_id, d.sha256 or "") for d in experiment.datasets)
    return cache_key(
        run_source=run_source,
        image_ref=_resolve_image_ref(ot_dir, experiment),
        command=experiment.command or "python run.py",
        inputs={"datasets": datasets} if datasets else None,
    )


def _try_cache_hit(
    ot_dir: Path, experiment: Experiment, exp_dir: Path, key: str
) -> tuple[Experiment, int] | None:
    """Reuse a cached result if one exists for ``key``; else return ``None``."""
    from opentorus.execution.cache import lookup, restore

    entry = lookup(ot_dir, key)
    if entry is None:
        return None
    results_dir = exp_dir / "results"
    restore(ot_dir, key, results_dir)
    cached = yaml.safe_load((entry / "manifest.yaml").read_text(encoding="utf-8")) or {}

    manifest = ResultManifest.model_validate(cached)
    manifest.experiment_id = experiment.id
    manifest.start_time = _utcnow()
    manifest.end_time = _utcnow()
    manifest.cache_hit = True
    manifest.cache_key = key
    manifest.datasets = [ref.model_dump(mode="json") for ref in experiment.datasets]
    (results_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )

    experiment.status = manifest.status
    experiment.updated_at = _utcnow()
    _save_meta(ot_dir, experiment)
    _write_summary(ot_dir, experiment)
    log_action(
        ot_dir,
        "run_experiment",
        ok=manifest.exit_code == 0,
        args={"experiment_id": experiment.id, "command": experiment.command, "cache_hit": True},
    )
    return experiment, manifest.exit_code


def run_experiment(ot_dir: Path, exp_id: str, timeout: int = 120) -> tuple[Experiment, int]:
    experiment = get_experiment(ot_dir, exp_id)
    if experiment is None:
        raise OpenTorusError(f"No experiment with id '{exp_id}'.")

    config = _load_config(ot_dir)
    # Hard guarantees, enforced at the single execution choke point so a command
    # stored in a manifest cannot bypass the agent loop's permission policy.
    if config.agent.mode == "review":
        raise OpenTorusError(
            "Review mode is read-only; experiments cannot be run (exp_run is blocked)."
        )
    _assert_command_allowed(experiment.command, experiment.environment)

    root = ot_dir.parent
    exp_dir = ot_dir / experiment.path
    results_dir = exp_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    key = _cache_key_for(ot_dir, experiment, exp_dir)
    if config.execution.cache:
        cached = _try_cache_hit(ot_dir, experiment, exp_dir, key)
        if cached is not None:
            return cached

    experiment.status = "running"
    experiment.updated_at = _utcnow()
    _save_meta(ot_dir, experiment)

    start_time = _utcnow()
    result, provenance = _run_via_backend(ot_dir, config, experiment, exp_dir, timeout)
    end_time = _utcnow()

    results_dir = exp_dir / "results"
    (results_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (results_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")

    experiment.status = "completed" if result.exit_code == 0 else "failed"
    experiment.updated_at = _utcnow()
    _save_meta(ot_dir, experiment)

    git_commit, dirty = (
        _git_commit_dirty(root) if config.environment.capture_git_state else (None, None)
    )
    environment = _capture_environment(root, config, exp_dir)
    result_files = sorted(
        p.name for p in results_dir.iterdir() if p.is_file() and p.name != "manifest.yaml"
    )
    manifest = ResultManifest(
        experiment_id=exp_id,
        command=experiment.command or "python run.py",
        start_time=start_time,
        end_time=end_time,
        exit_code=result.exit_code,
        status=experiment.status,
        stdout_path="results/stdout.txt",
        stderr_path="results/stderr.txt",
        result_files=result_files,
        environment=environment,
        backend=provenance.backend,
        backend_version=provenance.backend_version,
        tool_environment=provenance.tool_environment,
        image_ref=provenance.image_ref,
        tool_versions=provenance.tool_versions,
        image_digest=provenance.image_digest,
        sif_cache=provenance.sif_cache,
        cache_hit=False,
        cache_key=key,
        datasets=[ref.model_dump(mode="json") for ref in experiment.datasets],
        git_commit=git_commit,
        dirty_git_state=dirty,
        random_seed=_extract_seed(result.stdout),
    )
    (results_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )

    # Populate the content-addressed cache so identical future runs are reused.
    if config.execution.cache and experiment.status == "completed":
        from opentorus.execution.cache import store

        store(ot_dir, key, results_dir)

    _write_summary(ot_dir, experiment)

    log_action(
        ot_dir,
        "run_experiment",
        ok=result.exit_code == 0,
        args={"experiment_id": exp_id, "command": experiment.command},
        stdout_summary=result.stdout.strip()[:500] or None,
        stderr_summary=result.stderr.strip()[:500] or None,
    )
    return experiment, result.exit_code
