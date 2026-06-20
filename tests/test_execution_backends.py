"""Tests for pluggable execution backends (Milestone 55).

Backend selection (auto/explicit) resolves with stubbed availability; container
argv (mounts, network, limits) is assembled correctly without running a real
container; an unavailable requested backend is reported honestly; the local
fallback works offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from opentorus.config import default_config
from opentorus.execution import (
    ApptainerBackend,
    DockerBackend,
    LocalBackend,
    Mount,
    PodmanBackend,
    RunLimits,
    select_backend,
)
from opentorus.execution import backends as backends_mod
from opentorus.execution.base import ExecutionRequest


def _req(tmp_path: Path, **kw) -> ExecutionRequest:
    base = {"command": "echo hi", "workdir": tmp_path}
    base.update(kw)
    return ExecutionRequest(**base)


def test_local_backend_runs_offline(tmp_path: Path) -> None:
    backend = LocalBackend()
    assert backend.is_available()
    req = _req(tmp_path, command=f"{sys.executable} -c \"print('ok')\"")
    result = backend.run(req)
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_docker_argv_defaults_no_network_and_workdir_mount(tmp_path: Path) -> None:
    argv = DockerBackend().build_argv(_req(tmp_path, image="julia:1.10", command="julia run.jl"))
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "--workdir" in argv and argv[argv.index("--workdir") + 1] == "/work"
    # Workspace is mounted read-write at /work; image precedes the command.
    assert f"{tmp_path}:/work" in argv
    assert "julia:1.10" in argv
    assert argv[-2:] == ["julia", "run.jl"]


def test_docker_argv_network_and_limits(tmp_path: Path) -> None:
    req = _req(
        tmp_path,
        image="img",
        network=True,
        limits=RunLimits(timeout=10, memory="2g", cpus="2"),
    )
    argv = DockerBackend().build_argv(req)
    assert "none" not in argv  # network requested → no isolation flag
    assert argv[argv.index("--memory") + 1] == "2g"
    assert argv[argv.index("--cpus") + 1] == "2"


def test_docker_extra_mounts_readonly(tmp_path: Path) -> None:
    req = _req(
        tmp_path,
        image="img",
        mounts=[Mount(source="/data", target="/data", read_only=True)],
    )
    argv = DockerBackend().build_argv(req)
    assert "/data:/data:ro" in argv


def test_podman_uses_podman_binary(tmp_path: Path) -> None:
    argv = PodmanBackend().build_argv(_req(tmp_path, image="img"))
    assert argv[0] == "podman"


def test_apptainer_argv_prefixes_docker_ref_and_isolates_net(tmp_path: Path) -> None:
    argv = ApptainerBackend().build_argv(_req(tmp_path, image="julia:1.10"))
    assert argv[:2] == ["apptainer", "exec"]
    assert "--net" in argv and "none" in argv
    assert "docker://julia:1.10" in argv
    assert f"{tmp_path}:/work" in " ".join(argv)


def test_apptainer_keeps_local_sif_image(tmp_path: Path) -> None:
    argv = ApptainerBackend().build_argv(_req(tmp_path, image="/images/julia.sif"))
    assert "/images/julia.sif" in argv
    assert "docker:///images/julia.sif" not in argv


def test_unavailable_container_backend_reported_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backends_mod, "_which", lambda binary: False)
    result = DockerBackend().run(_req(tmp_path, image="img"))
    assert result.exit_code == 127
    assert "unavailable" in result.stderr


def test_select_explicit_backend() -> None:
    config = default_config()
    config.execution.backend = "podman"
    assert select_backend(config).name == "podman"


def test_select_auto_plain_command_is_local() -> None:
    config = default_config()  # backend == "auto"
    assert select_backend(config, needs_image=False).name == "local"


def test_select_auto_image_picks_first_available(monkeypatch: pytest.MonkeyPatch) -> None:
    config = default_config()
    # Only podman is "installed".
    monkeypatch.setattr(backends_mod, "_which", lambda binary: binary == "podman")
    assert select_backend(config, needs_image=True).name == "podman"


def test_select_auto_image_falls_back_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    config = default_config()
    monkeypatch.setattr(backends_mod, "_which", lambda binary: False)
    assert select_backend(config, needs_image=True).name == "local"
