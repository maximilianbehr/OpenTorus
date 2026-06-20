"""Tests for remote / HPC execution backends (Milestone 65).

Argv and sbatch scripts are assembled correctly (asserted, not executed); a
stubbed remote run returns the standard ShellResult shape; a missing host is
reported honestly. Offline — no cluster, no SSH.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.execution.base import ExecutionRequest, RunLimits
from opentorus.execution.registry import make_backend, select_backend
from opentorus.execution.remote import RemoteBackend, SlurmBackend
from opentorus.tools.shell import ShellResult


def _request(tmp_path: Path) -> ExecutionRequest:
    workdir = tmp_path / "EXP-0001"
    (workdir / "results").mkdir(parents=True, exist_ok=True)
    return ExecutionRequest(command="python run.py", workdir=workdir, limits=RunLimits(timeout=30))


class StubRunner:
    """Records argv and returns a canned result per call."""

    def __init__(self, *results: ShellResult) -> None:
        self.calls: list[list[str]] = []
        default = [ShellResult(command="", stdout="ok", stderr="", exit_code=0)]
        self._results = list(results) or default

    def __call__(self, argv, *args, **kwargs) -> ShellResult:  # noqa: ANN001
        self.calls.append(list(argv))
        return self._results[min(len(self.calls) - 1, len(self._results) - 1)]


def test_ssh_build_argv_wraps_remote_cd(tmp_path: Path) -> None:
    backend = RemoteBackend(host="cluster", user="me", remote_root="/scratch/runs")
    argv = backend.build_argv(_request(tmp_path))
    assert argv[0] == "ssh"
    assert argv[1] == "me@cluster"
    assert "cd /scratch/runs/EXP-0001 && python run.py" == argv[2]


def test_ssh_stage_and_fetch_argv(tmp_path: Path) -> None:
    backend = RemoteBackend(host="cluster", remote_root="/scratch/runs")
    request = _request(tmp_path)
    stage = backend.stage_argv(request)
    assert stage[0] == "scp" and "-r" in stage
    assert stage[-1] == "cluster:/scratch/runs/"
    fetch = backend.fetch_argv(request)
    assert fetch[-2] == "cluster:/scratch/runs/EXP-0001/results"


def test_ssh_run_returns_standard_shape(tmp_path: Path) -> None:
    runner = StubRunner(
        ShellResult(command="stage", stdout="", stderr="", exit_code=0),
        ShellResult(command="run", stdout="metric=1", stderr="", exit_code=0),
        ShellResult(command="fetch", stdout="", stderr="", exit_code=0),
    )
    backend = RemoteBackend(host="cluster", runner=runner)
    # ssh is typically installed; force availability deterministically.
    backend.is_available = lambda: True  # type: ignore[method-assign]
    import opentorus.execution.remote as remote_mod

    orig = remote_mod.shutil.which
    remote_mod.shutil.which = lambda _b: "/usr/bin/ssh"  # type: ignore[assignment]
    try:
        result = backend.run(_request(tmp_path))
    finally:
        remote_mod.shutil.which = orig
    assert isinstance(result, ShellResult)
    assert result.stdout == "metric=1"
    assert len(runner.calls) == 3  # stage, run, fetch


def test_slurm_sbatch_script_has_directives(tmp_path: Path) -> None:
    backend = SlurmBackend(
        host="hpc", user="me", remote_root="/scratch", partition="gpu", time_limit="01:00:00"
    )
    script = backend.build_sbatch_script(_request(tmp_path))
    assert script.startswith("#!/bin/bash")
    assert "#SBATCH --partition=gpu" in script
    assert "#SBATCH --time=01:00:00" in script
    assert "cd /scratch/EXP-0001" in script
    assert script.rstrip().endswith("python run.py")


def test_slurm_submit_argv_uses_sbatch_parsable(tmp_path: Path) -> None:
    backend = SlurmBackend(host="hpc", remote_root="/scratch")
    argv = backend.build_submit_argv(_request(tmp_path))
    assert argv[0] == "ssh" and argv[1] == "hpc"
    assert argv[2] == "sbatch --parsable /scratch/EXP-0001/opentorus_job.sbatch"


def test_missing_host_reported_honestly(tmp_path: Path) -> None:
    backend = RemoteBackend(host=None)
    result = backend.run(_request(tmp_path))
    assert result.exit_code == 127
    assert "No remote host configured" in result.stderr


def test_select_backend_resolves_remote_from_config(tmp_path: Path) -> None:
    config = default_config()
    config.execution.backend = "slurm"
    config.execution.remote.host = "hpc"
    backend = select_backend(config, needs_image=False)
    assert isinstance(backend, SlurmBackend)
    assert backend.host == "hpc"
    # make_backend requires config for remote backends.
    assert isinstance(make_backend("ssh", config), RemoteBackend)


def test_remote_backend_without_config_raises() -> None:
    try:
        make_backend("ssh")
        raise AssertionError("expected an error without config")
    except ValueError as exc:
        assert "requires a config" in str(exc)
