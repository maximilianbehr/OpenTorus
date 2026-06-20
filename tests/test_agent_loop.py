"""Tests for the agent loop with the mock provider (Milestone 10)."""

from __future__ import annotations

from pathlib import Path

from opentorus.actions import list_actions
from opentorus.agent.loop import AgentLoop
from opentorus.agent.session import read_messages
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


def _loop(tmp_path: Path) -> AgentLoop:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    return AgentLoop(tmp_path, ot_dir, MockProvider(), registry, default_config())


def test_finite_max_steps_is_a_hard_cap(tmp_path: Path) -> None:
    # A finite max_steps caps a provider that never returns a final message.
    # (max_steps=inf is intentionally unbounded — the no-progress stall guard and
    # Ctrl-C are the stops there; see tests/test_task_cycle_guard.py.)
    from opentorus.providers.base import BaseProvider, ProviderResponse

    class _NeverFinishes(BaseProvider):
        name = "never"

        def generate(self, messages, tools=None):  # type: ignore[override]
            return ProviderResponse(kind="tool_call", tool_name="status", tool_args={})

    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    loop = AgentLoop(tmp_path, ot_dir, _NeverFinishes(), registry, default_config(), max_steps=5)
    loop.run("loop until cap")
    assert loop.hit_max_steps is True
    assert loop.steps_run == 5


def test_status_task_runs_tool_and_persists(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    answer = loop.run("show me the status")
    assert "workspace_root" in answer
    assert "Validation not run" in answer

    ot_dir = workspace_dir(tmp_path)
    roles = [m.role for m in read_messages(ot_dir)]
    assert "user" in roles and "tool" in roles and "assistant" in roles
    assert list_actions(ot_dir)[-1].tool_name == "status"


def test_memory_task_uses_memory_tool(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    answer = loop.run("what is in memory?")
    assert "memory" in answer.lower()
    assert list_actions(workspace_dir(tmp_path))[-1].tool_name == "memory_list"


def test_plain_task_returns_direct_message(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    answer = loop.run("hello there")
    assert "mock provider" in answer.lower()
    # A direct answer should not have invoked any tool.
    assert list_actions(workspace_dir(tmp_path)) == []


def test_diff_task_uses_git_diff_tool(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop.run("show the diff")
    assert list_actions(workspace_dir(tmp_path))[-1].tool_name == "git_diff"
