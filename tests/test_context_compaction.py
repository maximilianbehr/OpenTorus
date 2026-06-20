"""Tests that build_messages triggers session compaction."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.context import build_messages
from opentorus.agent.session import SessionMessage, append_message, read_messages
from opentorus.config import default_config
from opentorus.workspace import init_workspace, workspace_dir


def test_build_messages_triggers_session_compaction(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    root = tmp_path
    config = default_config()
    config.context.token_budget = 200
    config.context.compaction_threshold = 0.5
    config.context.compaction_llm = False

    for i in range(10):
        append_message(ot, SessionMessage(role="user", content=f"long task {i} " * 25))
        append_message(ot, SessionMessage(role="assistant", content=f"long answer {i} " * 25))

    before = len(read_messages(ot))
    build_messages(root, ot, config, ["status"])
    after = len(read_messages(ot))
    assert after < before
    assert any(m.metadata.get("compaction") for m in read_messages(ot))
