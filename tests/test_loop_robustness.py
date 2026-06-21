"""Tests for batch-7 agent-loop robustness fixes."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.compaction import compact_messages
from opentorus.agent.session import SessionMessage
from opentorus.config import default_config
from opentorus.workspace import init_workspace, workspace_dir


def test_status_is_never_repeat_blocked() -> None:
    # status reports the live inventory the agent re-polls after writes; it must be
    # re-run, not hard-blocked on repeat.
    from opentorus.agent.loop import _REPEAT_GUARD_EXEMPT

    assert "status" in _REPEAT_GUARD_EXEMPT


def test_compaction_floor_preserves_recent_turns_under_large_head(tmp_path: Path) -> None:
    # A large system head must not starve recent conversation: the most recent turn
    # survives compaction even when the head is big.
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.context.token_budget = 200
    big_head = SessionMessage(role="system", content="HEAD inventory line " * 200)
    msgs = [big_head] + [
        SessionMessage(role="user", content="question " * 5),
        SessionMessage(role="assistant", content="answer " * 5),
        SessionMessage(role="user", content="follow up " * 5),
        SessionMessage(role="assistant", content="final recent turn " * 3),
    ]
    out = compact_messages(ot, msgs, config)
    assert out[-1] == msgs[-1]  # the most recent turn is preserved, not starved


def test_retrieval_breaker_reset_helper_exists() -> None:
    from opentorus.agent.context import reset_retrieval_breaker

    reset_retrieval_breaker()  # callable, resets to a clean state
