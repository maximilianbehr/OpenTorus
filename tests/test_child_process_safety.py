"""Child processes: no credentials in their environment, no survivors after a timeout.

Pins items 6a (clean env for run_shell / local experiments), 6b (Apptainer
``--containall --cleanenv``, truthful mounts) and 6c (process-group kill).
"""

from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from opentorus.execution import ApptainerBackend, DockerBackend, LocalBackend
from opentorus.execution.base import ExecutionRequest, RunLimits
from opentorus.tools.base import ToolCall
from opentorus.tools.builtin import RunShellTool
from opentorus.tools.childenv import clean_env, is_credential_name, scrubbed_env
from opentorus.tools.shell import run_argv, run_shell

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX process groups / procfs")

_SECRET = "sk-test-SECRETVALUE-0123456789abcdef"


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", _SECRET)
    monkeypatch.setenv("MY_SERVICE_TOKEN", _SECRET)
    monkeypatch.setenv("DB_PASSWORD", _SECRET)
    monkeypatch.setenv("SOME_CLIENT_SECRET", _SECRET)
    monkeypatch.setenv("OPENTORUS_HARMLESS_FLAG", "visible-in-scrubbed")


@pytest.mark.parametrize(
    "name",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "HF_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "NPM_TOKEN",
        "DB_PASSWORD",
        "MYPASSWORD",
        "GITLAB_PAT",
        "SERVICE_APIKEY",
        "private_key_path",
        "SOME_CLIENT_SECRET",
    ],
)
def test_credential_names_are_recognised(name: str) -> None:
    assert is_credential_name(name)


@pytest.mark.parametrize(
    "name",
    ["PATH", "HOME", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "SSH_AUTH_SOCK", "MONKEY", "KEYBOARD"],
)
def test_ordinary_names_are_not_credentials(name: str) -> None:
    assert not is_credential_name(name)


def test_clean_env_is_an_allowlist_and_never_carries_credentials() -> None:
    environ = {
        "PATH": "/bin",
        "HOME": "/h",
        "LC_ALL": "C",
        "OMP_NUM_THREADS": "2",
        "RANDOM_VAR": "x",
        "OPENAI_API_KEY": _SECRET,
    }
    env = clean_env(environ=environ)
    assert env == {"PATH": "/bin", "HOME": "/h", "LC_ALL": "C", "OMP_NUM_THREADS": "2"}
    # An allowlist pattern can add names -- but never a credential.
    env = clean_env(environ=environ, allowlist=["RANDOM_*", "OPENAI_*"])
    assert env["RANDOM_VAR"] == "x"
    assert "OPENAI_API_KEY" not in env
    # Explicit extra values are stripped of credentials too.
    assert "HF_TOKEN" not in clean_env({"HF_TOKEN": _SECRET}, environ=environ)


def test_scrubbed_env_keeps_ordinary_names(secret_env: None) -> None:
    env = scrubbed_env()
    assert env["OPENTORUS_HARMLESS_FLAG"] == "visible-in-scrubbed"
    assert _SECRET not in "".join(env.values())


@posix_only
def test_run_shell_child_cannot_read_secret_from_proc_environ(
    secret_env: None, tmp_path: Path
) -> None:
    if not Path("/proc/self/environ").exists():
        pytest.skip("no procfs")
    result = run_shell("cat /proc/self/environ", cwd=tmp_path, env_policy="clean")
    assert result.exit_code == 0
    assert "PATH=" in result.stdout
    assert _SECRET not in result.stdout
    assert "OPENAI_API_KEY" not in result.stdout
    assert "OPENTORUS_HARMLESS_FLAG" not in result.stdout  # not allowlisted


def test_run_shell_tool_child_env_lacks_secrets(secret_env: None, tmp_path: Path) -> None:
    tool = RunShellTool(tmp_path)
    script = "import os,sys; sys.stdout.write(repr(sorted(os.environ.items())))"
    (tmp_path / "dump.py").write_text(script, encoding="utf-8")
    result = tool.run(ToolCall(name="run_shell", args={"command": f"{sys.executable} dump.py"}))
    assert result.ok, result.content
    assert _SECRET not in result.content
    assert "MY_SERVICE_TOKEN" not in result.content


def test_run_shell_tool_honours_configured_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("JULIA_DEPOT_PATH", "/opt/julia")
    tool = RunShellTool(tmp_path, env_allowlist=["JULIA_*"])
    (tmp_path / "e.py").write_text(
        "import os; print(os.environ.get('JULIA_DEPOT_PATH'))", encoding="utf-8"
    )
    result = tool.run(ToolCall(name="run_shell", args={"command": f"{sys.executable} e.py"}))
    assert "/opt/julia" in result.content


def test_scrubbed_run_argv_still_drops_secrets(secret_env: None, tmp_path: Path) -> None:
    result = run_argv([sys.executable, "-c", "import os; print(sorted(os.environ))"], cwd=tmp_path)
    assert "OPENTORUS_HARMLESS_FLAG" in result.stdout
    assert "OPENAI_API_KEY" not in result.stdout
    assert "DB_PASSWORD" not in result.stdout


def test_local_backend_child_env_lacks_secrets(secret_env: None, tmp_path: Path) -> None:
    request = ExecutionRequest(
        command=f'{sys.executable} -c "import os; print(sorted(os.environ.items()))"',
        workdir=tmp_path,
        env={"SEED": "7", "LEAKED_TOKEN": _SECRET},
        network=True,
    )
    result = LocalBackend().run(request)
    assert result.exit_code == 0, result.stderr
    assert "'SEED', '7'" in result.stdout
    assert _SECRET not in result.stdout


# --- 6b: Apptainer ----------------------------------------------------------------


def test_apptainer_runs_contained_with_clean_env(tmp_path: Path) -> None:
    request = ExecutionRequest(command="python run.py", workdir=tmp_path, image="julia:1.10")
    argv = ApptainerBackend().build_argv(request)
    assert argv[:2] == ["apptainer", "exec"]
    assert "--containall" in argv
    assert "--cleanenv" in argv
    # The workspace bind keeps working.
    assert f"{tmp_path.as_posix()}:/work" in argv
    assert argv[argv.index("--pwd") + 1] == "/work"


def test_workspace_store_is_bound_read_only_over_a_writable_workdir(tmp_path: Path) -> None:
    (tmp_path / ".opentorus").mkdir()
    request = ExecutionRequest(command="python run.py", workdir=tmp_path, image="python:3.12")
    docker = DockerBackend().build_argv(request)
    assert f"{tmp_path.as_posix()}:/work" in docker
    assert f"{(tmp_path / '.opentorus').as_posix()}:/work/.opentorus:ro" in docker
    apptainer = ApptainerBackend().build_argv(request)
    assert f"{(tmp_path / '.opentorus').as_posix()}:/work/.opentorus:ro" in apptainer


def test_backends_docstring_states_the_writable_workdir() -> None:
    from opentorus.execution import backends

    doc = backends.__doc__ or ""
    assert "read-only workspace mount" not in doc
    assert "read-write" in doc


# --- 6c: no survivors -------------------------------------------------------------


def _spawner(tmp_path: Path) -> tuple[Path, Path]:
    pidfile = tmp_path / "grandchild.pid"
    script = tmp_path / "spawn.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import subprocess, sys, time
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            open({str(pidfile)!r}, "w").write(str(child.pid))
            time.sleep(120)
            """
        ),
        encoding="utf-8",
    )
    return script, pidfile


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); it is not running.
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():
        try:
            return stat.read_text().split(")")[-1].split()[0] != "Z"
        except OSError:
            return False
    return True


def _wait_dead(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


@posix_only
def test_timeout_kills_the_grandchild(tmp_path: Path) -> None:
    script, pidfile = _spawner(tmp_path)
    started = time.monotonic()
    result = run_argv([sys.executable, str(script)], cwd=tmp_path, timeout=1.5)
    assert result.timed_out and result.exit_code == 124
    assert time.monotonic() - started < 10
    grandchild = int(pidfile.read_text())
    assert _wait_dead(grandchild), "grandchild survived the timeout"


@posix_only
def test_local_backend_timeout_kills_the_grandchild(tmp_path: Path) -> None:
    script, pidfile = _spawner(tmp_path)
    request = ExecutionRequest(
        command=f"{sys.executable} {script}",
        workdir=tmp_path,
        network=True,
        limits=RunLimits(timeout=2),
    )
    result = LocalBackend().run(request)
    assert result.timed_out
    assert _wait_dead(int(pidfile.read_text()))


@posix_only
def test_background_leftover_is_reaped_after_normal_exit(tmp_path: Path) -> None:
    pidfile = tmp_path / "bg.pid"
    script = tmp_path / "bg.py"
    script.write_text(
        "import subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],"
        " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n",
        encoding="utf-8",
    )
    result = run_argv([sys.executable, str(script)], cwd=tmp_path, timeout=20)
    assert result.exit_code == 0 and not result.timed_out
    assert _wait_dead(int(pidfile.read_text()))


@posix_only
def test_exit_code_and_output_are_preserved(tmp_path: Path) -> None:
    result = run_argv(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); exit(3)"],
        cwd=tmp_path,
    )
    assert result.exit_code == 3
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"


def test_missing_binary_is_127(tmp_path: Path) -> None:
    result = run_argv(["definitely-not-a-binary-xyz"], cwd=tmp_path)
    assert result.exit_code == 127
