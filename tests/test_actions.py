"""Tests for the action log (Milestone 3)."""

from __future__ import annotations

from pathlib import Path

from opentorus.actions import list_actions, log_action
from opentorus.workspace import init_workspace, workspace_dir


def test_log_and_list_actions(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    a1 = log_action(base, "read_file", ok=True, args={"path": "pyproject.toml"})
    a2 = log_action(
        base, "run_shell", ok=False, args={"cmd": "pytest -q"}, stderr_summary="1 failure"
    )

    assert a1.id == "ACTION-0001"
    assert a2.id == "ACTION-0002"

    actions = list_actions(base)
    assert [a.tool_name for a in actions] == ["read_file", "run_shell"]
    assert actions[1].ok is False


def test_list_actions_respects_limit(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    for i in range(5):
        log_action(base, f"tool_{i}", ok=True)
    recent = list_actions(base, limit=2)
    assert [a.tool_name for a in recent] == ["tool_3", "tool_4"]
