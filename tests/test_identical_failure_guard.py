"""The identical-failure backstop in the agent loop.

A tool call that ran but failed used to count as progress (it reset the chat-only
streak), so with ``max_steps=inf`` a model re-issuing the same doomed call against
the same error cycled forever (observed: 60 identical ``proof_write`` rejections).
These tests pin the guard: warn from the third identical failure, stop honestly at
the cap, and never trip on varying failures.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import _MAX_IDENTICAL_FAILURES, AgentLoop
from opentorus.agent.session import read_messages
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class _RepeatCall(BaseProvider):
    """Scripted provider cycling through a fixed list of tool calls, forever."""

    name = "repeat"

    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self._calls = calls
        self._i = 0

    def generate(self, messages, tools=None):  # type: ignore[override]
        name, args = self._calls[self._i % len(self._calls)]
        self._i += 1
        return ProviderResponse(kind="tool_call", tool_name=name, tool_args=args)


def _loop(tmp_path: Path, provider: BaseProvider, max_steps: float = 50) -> AgentLoop:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir, default_config())
    return AgentLoop(tmp_path, ot_dir, provider, registry, default_config(), max_steps=max_steps)


def test_identical_failures_stop_the_run(tmp_path: Path) -> None:
    loop = _loop(tmp_path, _RepeatCall([("exp_run", {"exp_id": "EXP-9999"})]))
    answer = loop.run("run the experiment")
    assert "Stopped" in answer and "exp_run" in answer
    assert loop.steps_run == _MAX_IDENTICAL_FAILURES
    assert loop.hit_max_steps is False


def test_model_is_warned_before_the_stop(tmp_path: Path) -> None:
    loop = _loop(tmp_path, _RepeatCall([("exp_run", {"exp_id": "EXP-9999"})]))
    loop.run("run the experiment")
    tool_msgs = [m.content for m in read_messages(workspace_dir(tmp_path)) if m.role == "tool"]
    assert len(tool_msgs) == _MAX_IDENTICAL_FAILURES
    assert "[loop guard]" not in tool_msgs[0]
    assert "[loop guard]" not in tool_msgs[1]
    assert all("[loop guard]" in m for m in tool_msgs[2:])


def test_varying_failures_do_not_trip_the_backstop(tmp_path: Path) -> None:
    calls = [("exp_run", {"exp_id": "EXP-9998"}), ("exp_run", {"exp_id": "EXP-9999"})]
    loop = _loop(tmp_path, _RepeatCall(calls), max_steps=8)
    answer = loop.run("run the experiments")
    assert "Stopped" not in answer
    assert loop.hit_max_steps is True


def test_identical_schema_errors_also_counted(tmp_path: Path) -> None:
    # A schema-invalid call repeated verbatim is the same unwinnable cycle.
    loop = _loop(tmp_path, _RepeatCall([("exp_run", {})]))
    answer = loop.run("run the experiment")
    assert "Stopped" in answer
    assert loop.steps_run == _MAX_IDENTICAL_FAILURES


def test_noop_apply_patch_is_a_failure_not_empty_success(tmp_path: Path) -> None:
    # Forensic finding (perfect-mirsky run): apply_patch with old == new returned
    # ok("") — a blank tool message with zero signal, provoking verbatim re-issues
    # invisible to every guard. A no-op patch must be a failure with a clear message.
    from opentorus.tools.base import ToolCall
    from opentorus.tools.builtin import ApplyPatchTool

    init_workspace(tmp_path)
    target = tmp_path / "script.py"
    target.write_text("x = 1\n", encoding="utf-8")
    tool = ApplyPatchTool(tmp_path)
    result = tool.run(
        ToolCall(name="apply_patch", args={"path": "script.py", "old": "x = 1", "new": "x = 1"})
    )
    assert result.ok is False
    assert "no change" in result.content
    assert target.read_text(encoding="utf-8") == "x = 1\n"  # file untouched

    # A real patch still succeeds and never returns empty content.
    result = tool.run(
        ToolCall(name="apply_patch", args={"path": "script.py", "old": "x = 1", "new": "x = 2"})
    )
    assert result.ok is True and result.content.strip()


def test_identical_gate_blocks_count_toward_the_stop(tmp_path: Path) -> None:
    # Blocked calls used to bypass the identical-failure tracker entirely: a model
    # hammering the same gated call was invisible to every guard. Now six identical
    # gate rejections end the run honestly.
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir, default_config())
    loop = AgentLoop(
        tmp_path,
        ot_dir,
        _RepeatCall([("memory_list", {})]),
        registry,
        default_config(),
        max_steps=50,
        tool_gate=lambda name, args: (
            "Blocked: not in this phase." if name == "memory_list" else None
        ),
    )
    answer = loop.run("list memory")
    assert "Stopped" in answer
    assert loop.steps_run == _MAX_IDENTICAL_FAILURES
    from opentorus.actions import list_actions

    acts = list_actions(ot_dir)
    assert len(acts) == _MAX_IDENTICAL_FAILURES  # every block is in the audit trail
    assert all(not a.ok for a in acts)
