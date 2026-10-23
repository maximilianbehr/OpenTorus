"""Fail-closed local confinement (6d): bwrap --unshare-net, rlimits, refuse when required."""

from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

import pytest

from opentorus.execution import backends
from opentorus.execution.backends import LocalBackend, bwrap_prefix, parse_memory
from opentorus.execution.base import ExecutionRequest, RunLimits
from opentorus.execution.registry import select_backend

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX confinement")
needs_bwrap = pytest.mark.skipif(not backends.bwrap_usable(), reason="bubblewrap not usable")


@pytest.fixture
def listener():  # noqa: ANN201
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def accept() -> None:
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                conn.close()
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield port
    stop.set()
    srv.close()


def _connect_cmd(tmp_path: Path, port: int) -> str:
    script = tmp_path / "connect.py"
    script.write_text(
        "import socket, sys\n"
        "try:\n"
        f"    socket.create_connection(('127.0.0.1', {port}), timeout=3).close()\n"
        "    print('CONNECTED')\n"
        "except OSError as exc:\n"
        "    print('REFUSED', exc)\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {script}"


@posix_only
@needs_bwrap
def test_no_network_request_cannot_reach_a_host_service(tmp_path: Path, listener: int) -> None:
    cmd = _connect_cmd(tmp_path, listener)
    backend = LocalBackend()
    confined = backend.run(ExecutionRequest(command=cmd, workdir=tmp_path, network=False))
    assert "REFUSED" in confined.stdout, confined.stdout + confined.stderr
    assert backend.last_confinement == "bwrap"
    opened = backend.run(ExecutionRequest(command=cmd, workdir=tmp_path, network=True))
    assert "CONNECTED" in opened.stdout
    assert backend.last_confinement == "none"


@posix_only
@needs_bwrap
def test_confined_run_still_reads_and_writes_the_workdir(tmp_path: Path) -> None:
    (tmp_path / "in.txt").write_text("41", encoding="utf-8")
    cmd = f"{sys.executable} -c \"open('out.txt','w').write(str(int(open('in.txt').read())+1))\""
    result = LocalBackend().run(ExecutionRequest(command=cmd, workdir=tmp_path))
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "42"


def test_require_refuses_when_confinement_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backends, "bwrap_usable", lambda: False)
    marker = tmp_path / "ran"
    cmd = f"{sys.executable} -c \"open({str(marker)!r},'w')\""
    result = LocalBackend(confinement="require").run(
        ExecutionRequest(command=cmd, workdir=tmp_path, network=False)
    )
    assert result.exit_code == 126
    assert "not executed" in result.stderr and "bwrap" in result.stderr
    assert not marker.exists()
    # auto degrades to an unconfined run (documented), off never wraps.
    auto = LocalBackend(confinement="auto").run(
        ExecutionRequest(command=cmd, workdir=tmp_path, network=False)
    )
    assert auto.exit_code == 0 and marker.exists()


def test_config_selects_the_confinement_mode(tmp_path: Path) -> None:
    from opentorus.config import default_config

    config = default_config()
    assert config.execution.local_confinement == "auto"
    config.execution.local_confinement = "require"
    backend = select_backend(config)
    assert isinstance(backend, LocalBackend) and backend.confinement == "require"


@posix_only
def test_memory_limit_is_enforced(tmp_path: Path) -> None:
    cmd = f"{sys.executable} -c \"x = bytearray(400 * 1024 * 1024); print('ALLOCATED')\""
    result = LocalBackend(confinement="off").run(
        ExecutionRequest(
            command=cmd, workdir=tmp_path, network=True, limits=RunLimits(memory="200m")
        )
    )
    assert "ALLOCATED" not in result.stdout
    assert result.exit_code != 0


@posix_only
@pytest.mark.skipif(not hasattr(os, "sched_getaffinity"), reason="no affinity API")
def test_cpus_limit_pins_affinity(tmp_path: Path) -> None:
    cmd = f'{sys.executable} -c "import os; print(len(os.sched_getaffinity(0)))"'
    result = LocalBackend(confinement="off").run(
        ExecutionRequest(command=cmd, workdir=tmp_path, network=True, limits=RunLimits(cpus="1"))
    )
    assert result.stdout.strip() == "1"


def test_bad_memory_limit_is_refused(tmp_path: Path) -> None:
    result = LocalBackend(confinement="off").run(
        ExecutionRequest(command="true", workdir=tmp_path, limits=RunLimits(memory="lots"))
    )
    assert result.exit_code == 126 and "memory" in result.stderr.lower()


def test_parse_memory_units() -> None:
    assert parse_memory("512m") == 512 * 1024**2
    assert parse_memory("2g") == 2 * 1024**3
    assert parse_memory("1GiB") == 1024**3
    assert parse_memory("4096") == 4096


def test_bwrap_prefix_hides_run_and_unshares_net(tmp_path: Path) -> None:
    argv = bwrap_prefix(tmp_path)
    assert "--unshare-net" in argv and "--die-with-parent" in argv
    assert argv[argv.index("--tmpfs") + 1] == "/run"
    assert argv[argv.index("--chdir") + 1] == str(tmp_path)


@posix_only
@needs_bwrap
def test_confined_timeout_still_kills_descendants(tmp_path: Path) -> None:
    from test_child_process_safety import _spawner, _wait_dead

    script, pidfile = _spawner(tmp_path)
    result = LocalBackend().run(
        ExecutionRequest(
            command=f"{sys.executable} {script}",
            workdir=tmp_path,
            network=False,
            limits=RunLimits(timeout=2),
        )
    )
    assert result.timed_out
    assert _wait_dead(int(pidfile.read_text()))
