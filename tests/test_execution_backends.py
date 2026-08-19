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
    # Mount sources are POSIX-form on every host (C:/-style on Windows).
    assert f"{tmp_path.as_posix()}:/work" in argv
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
    assert f"{tmp_path.as_posix()}:/work" in " ".join(argv)


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


def test_docker_run_kills_the_named_container_when_the_client_times_out(
    tmp_path: Path, monkeypatch
) -> None:
    """A timeout kills the ``docker run`` client, not the container. The backend names
    the container and issues ``docker kill <name>`` whenever the client did not exit
    cleanly (timeout or interrupt), and never after a clean exit."""
    from opentorus.execution import backends as backends_mod
    from opentorus.tools.shell import ShellResult

    seen: dict[str, object] = {"argv": None, "killed": []}

    def _fake_run_argv(argv, cwd=None, timeout=60, *, label=None, env=None):  # noqa: ANN001, ANN202
        seen["argv"] = list(argv)
        return ShellResult(
            command=label or "", stdout="", stderr="t/o", exit_code=124, timed_out=True
        )

    def _fake_subprocess_run(argv, **kwargs):  # noqa: ANN001, ANN202
        seen["killed"].append(list(argv))  # type: ignore[union-attr]

        class _Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Done()

    backend = DockerBackend()
    monkeypatch.setattr(backend, "is_available", lambda: True)
    monkeypatch.setattr(backends_mod, "run_argv", _fake_run_argv)
    monkeypatch.setattr(backends_mod.subprocess, "run", _fake_subprocess_run)
    result = backend.run(_req(tmp_path, image="img", command="python long.py"))
    assert result.timed_out
    argv = seen["argv"]
    assert "--name" in argv  # type: ignore[operator]
    name = argv[argv.index("--name") + 1]  # type: ignore[index]
    assert name.startswith("opentorus-")
    assert seen["killed"] == [["docker", "kill", name]]

    # clean exit: no kill
    seen["killed"] = []
    monkeypatch.setattr(
        backends_mod,
        "run_argv",
        lambda argv, cwd=None, timeout=60, *, label=None, env=None: ShellResult(
            command=label or "", stdout="ok", stderr="", exit_code=0
        ),
    )
    assert backend.run(_req(tmp_path, image="img", command="python ok.py")).exit_code == 0
    assert seen["killed"] == []
