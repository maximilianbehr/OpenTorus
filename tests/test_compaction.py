"""Tests for token-budget compaction (Milestone 29)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.compaction import (
    CompactionRecord,
    compact_messages,
    estimate_tokens,
    total_tokens,
)
from opentorus.agent.session import SessionMessage
from opentorus.config import default_config
from opentorus.jsonl import read_jsonl
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _convo(n: int) -> list[SessionMessage]:
    msgs = [SessionMessage(role="system", content="SYS PROMPT")]
    for i in range(n):
        msgs.append(SessionMessage(role="user", content=f"please do task number {i} " * 10))
        msgs.append(SessionMessage(role="assistant", content=f"working on task {i} " * 10))
    return msgs


def test_estimate_tokens_monotonic() -> None:
    assert estimate_tokens("x" * 40) > estimate_tokens("x" * 4)


def test_under_budget_unchanged(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = default_config()
    msgs = _convo(2)
    config.context.token_budget = 100000
    assert compact_messages(ot, msgs, config) == msgs


def test_disabled_unchanged(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = default_config()
    config.context.compaction_enabled = False
    config.context.token_budget = 1
    msgs = _convo(5)
    assert compact_messages(ot, msgs, config) == msgs


def test_over_budget_compacts_and_persists(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = default_config()
    config.context.token_budget = 120  # force compaction
    msgs = _convo(8)
    out = compact_messages(ot, msgs, config)

    assert len(out) < len(msgs)
    assert out[0].content == "SYS PROMPT"  # system head preserved
    assert any("Summary of earlier conversation" in m.content for m in out)
    assert out[-1] == msgs[-1]  # most recent turn preserved
    assert total_tokens(out) <= total_tokens(msgs)
    # Compaction is recorded as an inspectable artifact.
    records = read_jsonl(ot / "compaction" / "history.jsonl", CompactionRecord)
    assert len(records) == 1
    assert records[0].summarized_messages > 0


def test_summary_preserves_goals(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = default_config()
    config.context.token_budget = 80
    msgs = [
        SessionMessage(role="system", content="SYS"),
        SessionMessage(role="user", content="investigate the caching latency problem " * 5),
        SessionMessage(role="assistant", content="done analysing " * 20),
        SessionMessage(role="user", content="now write the report " * 5),
        SessionMessage(role="assistant", content="report written " * 5),
    ]
    out = compact_messages(ot, msgs, config)
    summary = next(m.content for m in out if "Summary of earlier conversation" in m.content)
    assert "caching" in summary.lower() or "Goals" in summary


def test_redacted_sensitive_not_leaked_into_summary(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = default_config()
    config.context.token_budget = 60
    # Simulate a turn that was already redacted by the privacy filter.
    msgs = [
        SessionMessage(role="system", content="SYS"),
        SessionMessage(role="user", content="read the env file " * 5),
        SessionMessage(role="tool", content="[redacted: sensitive content excluded]"),
        SessionMessage(role="user", content="continue " * 20),
        SessionMessage(role="assistant", content="ok " * 20),
    ]
    out = compact_messages(ot, msgs, config)
    joined = "\n".join(m.content for m in out)
    assert "SECRET" not in joined


def test_maybe_compact_session_rewrites_session_file(tmp_path: Path) -> None:
    from opentorus.agent.compaction import maybe_compact_session
    from opentorus.agent.session import append_message, read_messages

    ot = _ws(tmp_path)
    config = default_config()
    config.context.token_budget = 200
    config.context.compaction_threshold = 0.5
    config.context.compaction_llm = False

    for i in range(12):
        append_message(ot, SessionMessage(role="user", content=f"task {i} " * 20))
        append_message(ot, SessionMessage(role="assistant", content=f"answer {i} " * 20))

    before = len(read_messages(ot))
    assert before == 24
    assert maybe_compact_session(ot, config) is True
    after = read_messages(ot)
    assert len(after) < before
    assert any(m.metadata.get("compaction") for m in after)
    assert after[-1].content.startswith("answer 11")


def test_maybe_compact_session_skips_under_threshold(tmp_path: Path) -> None:
    from opentorus.agent.compaction import maybe_compact_session
    from opentorus.agent.session import append_message, read_messages

    ot = _ws(tmp_path)
    config = default_config()
    append_message(ot, SessionMessage(role="user", content="short"))
    assert maybe_compact_session(ot, config) is False
    assert len(read_messages(ot)) == 1
