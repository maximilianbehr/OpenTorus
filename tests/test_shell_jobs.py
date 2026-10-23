"""Background shell jobs (item 31) and the model-chosen run_shell timeout."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from opentorus.tools.base import ToolCall
from opentorus.tools.builtin import RunShellTool, build_default_registry
from opentorus.tools.jobs import JobManager, ShellJobsTool, drain_notices

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")


def _tools(tmp_path: Path, **kw: object) -> tuple[RunShellTool, ShellJobsTool, JobManager]:
    manager = JobManager(tmp_path / "jobs")
    return RunShellTool(tmp_path, jobs=manager, **kw), ShellJobsTool(manager), manager  # type: ignore[arg-type]


def _call(tool, **args):  # noqa: ANN001, ANN202
    return tool.run(ToolCall(name=tool.name, args=args))


def _wait(predicate, seconds: float = 10.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_background_returns_a_job_id_at_once_and_notifies(tmp_path: Path) -> None:
    shell, jobs, manager = _tools(tmp_path)
    script = tmp_path / "work.py"
    script.write_text("import time; time.sleep(0.5); print('result=42')\n", encoding="utf-8")
    started = time.monotonic()
    result = _call(shell, command=f"{sys.executable} {script}", background=True)
    assert result.ok and result.metadata["job_id"] == "JOB-1"
    assert time.monotonic() - started < 0.5  # returned before the work finished
    assert "JOB-1" in _call(jobs, action="list").content
    assert _wait(lambda: manager.get("JOB-1").exit_code is not None)  # type: ignore[union-attr]
    (notice,) = manager.drain()
    assert "JOB-1 finished" in notice and "exit 0" in notice
    assert manager.drain() == []  # announced once
    read = _call(jobs, action="read", job_id="JOB-1")
    assert "result=42" in read.content and "exit_code=0" in read.content


@posix_only
def test_stop_kills_the_whole_process_group(tmp_path: Path) -> None:
    shell, jobs, manager = _tools(tmp_path)
    pidfile = tmp_path / "child.pid"
    script = tmp_path / "spawn.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    _call(shell, command=f"{sys.executable} {script}", background=True)
    assert _wait(pidfile.exists)
    stopped = _call(jobs, action="stop", job_id="JOB-1")
    assert "stopped" in stopped.content
    child = int(pidfile.read_text())
    assert _wait(lambda: not _alive(child))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split(")")[-1].split()[0] == "Z")


@posix_only
def test_session_end_kills_running_jobs(tmp_path: Path) -> None:
    shell, _, manager = _tools(tmp_path)
    _call(shell, command=f'{sys.executable} -c "import time; time.sleep(120)"', background=True)
    job = manager.get("JOB-1")
    assert job is not None
    manager.close()
    assert job.exit_code is not None and not _alive(job.proc.pid)


def test_background_job_deadline(tmp_path: Path) -> None:
    shell, _, manager = _tools(tmp_path, max_timeout=1)
    _call(shell, command=f'{sys.executable} -c "import time; time.sleep(60)"', background=True)
    assert _wait(lambda: manager.get("JOB-1").exit_code is not None)  # type: ignore[union-attr]
    assert "timed out" in manager.drain()[0]


def test_job_limit(tmp_path: Path) -> None:
    manager = JobManager(tmp_path / "jobs", max_jobs=1)
    shell = RunShellTool(tmp_path, jobs=manager)
    sleep = f'{sys.executable} -c "import time; time.sleep(30)"'
    assert _call(shell, command=sleep, background=True).ok
    second = _call(shell, command=sleep, background=True)
    assert not second.ok and "already running" in second.content
    manager.close()


def test_background_job_env_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-job-SECRET-0123456789abcdef")
    shell, jobs, manager = _tools(tmp_path)
    _call(
        shell,
        command=f'{sys.executable} -c "import os; print(sorted(os.environ))"',
        background=True,
    )
    assert _wait(lambda: manager.get("JOB-1").exit_code is not None)  # type: ignore[union-attr]
    assert "OPENAI_API_KEY" not in _call(jobs, action="read", job_id="JOB-1").content


def test_model_chosen_timeout_is_capped(tmp_path: Path) -> None:
    shell, _, _ = _tools(tmp_path, max_timeout=1)
    result = _call(shell, command=f'{sys.executable} -c "import time; time.sleep(5)"', timeout=99)
    assert not result.ok and "exit_code=124" in result.content
    assert "capped at 1s" in result.content
    quick = _call(shell, command=f'{sys.executable} -c "print(1)"', timeout=1)
    assert quick.ok


def test_tool_description_carries_the_job_rules() -> None:
    text = RunShellTool(Path(".")).description + ShellJobsTool(JobManager()).description
    assert "never wait for a job in a loop or with sleep" in text.lower()
    assert "never detach a process (setsid, nohup)" in text.lower()


def test_registry_wires_jobs_and_notices(tmp_path: Path) -> None:
    from opentorus.config import default_config

    (tmp_path / ".opentorus").mkdir()
    registry = build_default_registry(tmp_path, tmp_path / ".opentorus", default_config())
    shell = registry.get("run_shell")
    assert registry.get("shell_jobs") is not None
    _call(shell, command=f"{sys.executable} -c \"print('hi')\"", background=True)
    manager = registry.get("shell_jobs").manager  # type: ignore[union-attr]
    assert _wait(lambda: manager.get("JOB-1").exit_code is not None)
    _wait(lambda: bool(manager._notices))  # noqa: SLF001
    notices = drain_notices(registry)
    assert notices and "JOB-1" in notices[0]
    assert (tmp_path / ".opentorus" / "jobs").is_dir()
