"""Tests for session replay (Milestone 19)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.agent.replay import last_session_id, list_session_ids, summarize_session
from opentorus.agent.session import SessionMessage, append_message
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_loop_tags_session_id_and_replay_summarizes(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    loop = AgentLoop(tmp_path, ot, MockProvider(), registry, default_config(), session_id="sess-1")
    loop.run("show me the status")

    assert "sess-1" in list_session_ids(ot)
    assert last_session_id(ot) == "sess-1"

    summary = summarize_session(ot, "sess-1")
    assert "Session sess-1" in summary
    assert "show me the status" in summary  # goal captured
    assert "status(" in summary  # tool action captured
    assert "Suggested next steps:" in summary


def test_replay_last_picks_most_recent_session(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    AgentLoop(tmp_path, ot, MockProvider(), registry, default_config(), session_id="a").run("hello")
    AgentLoop(tmp_path, ot, MockProvider(), registry, default_config(), session_id="b").run("hi")
    assert list_session_ids(ot) == ["a", "b"]
    assert "Session b" in summarize_session(ot)


def test_summarize_no_sessions(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    assert "No sessions recorded" in summarize_session(ot)


def test_failures_captured(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, SessionMessage(role="user", content="do x", metadata={"session_id": "s"}))
    append_message(
        ot,
        SessionMessage(
            role="assistant",
            content="",
            metadata={"session_id": "s", "tool_calls": [{"id": "1", "name": "bogus", "args": {}}]},
        ),
    )
    append_message(
        ot,
        SessionMessage(
            role="tool",
            content="Unknown tool: bogus",
            metadata={"session_id": "s", "tool_call_id": "1", "name": "bogus"},
        ),
    )
    summary = summarize_session(ot, "s")
    assert "Failures:" in summary
    assert "Unknown tool" in summary
