"""Tests for the guarded shell runner (Milestone 4)."""

from __future__ import annotations

import sys
from pathlib import Path

from opentorus.actions import list_actions
from opentorus.tools.shell import execute_command, run_shell
from opentorus.workspace import init_workspace, workspace_dir


def test_echo_runs() -> None:
    result = run_shell("echo hello")
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.timed_out is False


def test_python_version_runs() -> None:
    result = run_shell(f"{sys.executable} --version")
    assert result.exit_code == 0
    assert "Python" in (result.stdout + result.stderr)


def test_timeout_is_reported() -> None:
    result = run_shell(f'{sys.executable} -c "import time; time.sleep(5)"', timeout=1)
    assert result.timed_out is True
    assert result.exit_code == 124


def test_missing_binary_does_not_crash() -> None:
    result = run_shell("this_command_does_not_exist_12345")
    assert result.exit_code == 127


def test_execute_command_blocks_dangerous(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    decision, result = execute_command(ot_dir, "rm -rf /", "trusted")
    assert decision.risk_level == "blocked"
    assert result is None
    logged = list_actions(ot_dir)
    assert logged[-1].tool_name == "run_shell"
    assert logged[-1].ok is False


def test_execute_command_runs_harmless_and_logs(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    decision, result = execute_command(ot_dir, "echo hi", "ask")
    assert result is not None
    assert result.stdout.strip() == "hi"
    assert list_actions(ot_dir)[-1].ok is True


def test_execute_command_denied_when_confirmation_refused(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    decision, result = execute_command(
        ot_dir, "echo touch", "ask"
    )  # echo is harmless -> runs without confirm
    assert result is not None

    # A non-harmless command in ask mode requires confirmation; refuse it.
    decision2, result2 = execute_command(
        ot_dir, f'{sys.executable} -c "print(1)"', "ask", confirm=lambda d: False
    )
    assert decision2.requires_confirmation is True
    assert result2 is None
