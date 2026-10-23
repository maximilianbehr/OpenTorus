"""A cancelled batch records honest results: not executed vs outcome unknown."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.agent.loop import TOOL_NOT_EXECUTED, TOOL_OUTCOME_UNKNOWN, AgentLoop
from opentorus.agent.replay import summarize_session
from opentorus.agent.session import SessionMessage, read_messages
from opentorus.config import default_config
from opentorus.providers._convert import DANGLING_TOOL_RESULT, to_openai_messages
from opentorus.providers.base import ProviderResponse, ToolCallRequest
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir
from support.providers import ScriptedProvider, message


def _three_calls() -> ProviderResponse:
    return ProviderResponse(
        kind="tool_call",
        tool_calls=[
            ToolCallRequest(tool_name="status", tool_args={}, tool_call_id="c1"),
            ToolCallRequest(tool_name="memory_list", tool_args={}, tool_call_id="c2"),
            ToolCallRequest(tool_name="status", tool_args={"x": 1}, tool_call_id="c3"),
        ],
    )


def _setup(tmp_path: Path):
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.permissions.mode = "trusted"
    return ot, config, build_default_registry(tmp_path, config)


def _tool_results(ot: Path) -> dict[str, SessionMessage]:
    return {m.metadata["tool_call_id"]: m for m in read_messages(ot) if m.role == "tool"}


def test_cancel_mid_batch_records_not_executed_for_undispatched_calls(tmp_path: Path) -> None:
    ot, config, registry = _setup(tmp_path)
    flag = {"stop": False}
    loop = AgentLoop(
        tmp_path,
        ot,
        ScriptedProvider([_three_calls(), message("done")]),
        registry,
        config,
        max_steps=5,
        should_stop=lambda: flag["stop"],
    )
    original = loop._runner.execute_tool

    def _execute(name, args, call_id):  # noqa: ANN001
        outcome = original(name, args, call_id)
        flag["stop"] = True
        return outcome

    loop._runner.execute_tool = _execute  # type: ignore[method-assign]
    assert loop.run("go") == "[stopped] cancelled by caller"
    results = _tool_results(ot)
    assert set(results) == {"c1", "c2", "c3"}  # every call is paired
    assert results["c1"].content != TOOL_NOT_EXECUTED
    for cid in ("c2", "c3"):
        assert results[cid].content == TOOL_NOT_EXECUTED
        assert results[cid].metadata["unrun"] == "not_dispatched"
        assert results[cid].metadata["ok"] is False
    assert "unrun" not in results["c1"].metadata


def test_interrupt_while_running_records_outcome_unknown(tmp_path: Path) -> None:
    ot, config, registry = _setup(tmp_path)
    loop = AgentLoop(
        tmp_path, ot, ScriptedProvider([_three_calls()]), registry, config, max_steps=5
    )
    original = loop._runner.execute_tool

    def _execute(name, args, call_id):  # noqa: ANN001
        if call_id == "c2":
            raise KeyboardInterrupt
        return original(name, args, call_id)

    loop._runner.execute_tool = _execute  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        loop.run("go")
    results = _tool_results(ot)
    assert results["c2"].content == TOOL_OUTCOME_UNKNOWN
    assert results["c2"].metadata["unrun"] == "interrupted_while_running"
    assert results["c3"].content == TOOL_NOT_EXECUTED
    # Rebuilding the request uses the recorded results — no placeholder needed.
    wire = to_openai_messages(read_messages(ot))
    contents = [m["content"] for m in wire if m.get("role") == "tool"]
    assert TOOL_OUTCOME_UNKNOWN in contents and TOOL_NOT_EXECUTED in contents
    assert DANGLING_TOOL_RESULT not in contents
    # Replay only reads; it runs nothing.
    before = len(read_messages(ot))
    summarize_session(ot)
    assert len(read_messages(ot)) == before


def test_dangling_call_rebuilds_as_outcome_unknown() -> None:
    messages = [
        SessionMessage(role="user", content="go"),
        SessionMessage(
            role="assistant",
            content="",
            metadata={"tool_calls": [{"id": "x1", "name": "run_shell", "args": {}}]},
        ),
    ]
    wire = to_openai_messages(messages)
    tool = [m for m in wire if m.get("role") == "tool"]
    assert tool and tool[0]["content"] == DANGLING_TOOL_RESULT
    assert "outcome unknown" in DANGLING_TOOL_RESULT and "did not return" in DANGLING_TOOL_RESULT
