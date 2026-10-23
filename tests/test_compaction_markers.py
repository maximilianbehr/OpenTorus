"""Append-only compaction markers, the real-token trigger, and the checkpoint prompt."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent import compaction
from opentorus.agent.compaction import (
    active_messages,
    maybe_compact_session,
    read_active_messages,
    summary_body,
)
from opentorus.agent.replay import summarize_session
from opentorus.agent.session import SessionMessage, append_message, read_messages
from opentorus.config import default_config
from opentorus.providers.base import ProviderResponse, TokenUsage
from opentorus.workspace import init_workspace, workspace_dir
from support.providers import ScriptedProvider


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _config(budget: int = 200):
    config = default_config()
    config.context.token_budget = budget
    config.context.compaction_threshold = 0.5
    config.context.compaction_llm = False
    return config


def _fill(ot: Path, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        append_message(
            ot, SessionMessage(role="user", content=f"task {i} " * 20, metadata={"session_id": "s"})
        )
        append_message(
            ot,
            SessionMessage(
                role="assistant", content=f"answer {i} " * 20, metadata={"session_id": "s"}
            ),
        )


def test_checkpoint_prompt_keeps_failures_identifiers_and_drops_word_cap() -> None:
    prompt = compaction._LLM_SUMMARY_SYSTEM
    assert "What was tried and did NOT work, and why" in prompt
    assert "EXACTLY" in prompt and "file paths" in prompt and "error messages" in prompt
    assert "current state" in prompt.lower()
    assert "400 words" not in prompt


def test_summary_carries_the_resume_prefix(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _fill(ot, 12)
    assert maybe_compact_session(ot, _config()) is True
    marker = read_messages(ot)[-1]
    assert marker.content.startswith("Summary of earlier conversation")
    assert "record of what was already done" in marker.content
    assert "files written are on disk" in marker.content
    assert "do not repeat an approach" in marker.content
    assert "Check the current state before you rebuild" in marker.content
    assert summary_body(marker) == marker.metadata["summary"]


def test_old_sessions_without_markers_load_unchanged(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _fill(ot, 3)
    # An old, *rewritten* session: an inline summary with only the legacy flag.
    append_message(
        ot,
        SessionMessage(
            role="system", content="Summary of earlier …", metadata={"compaction": True}
        ),
    )
    raw = read_messages(ot)
    assert [m.content for m in active_messages(raw)] == [m.content for m in raw]


def test_replay_still_sees_compacted_turns(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _fill(ot, 12)
    assert maybe_compact_session(ot, _config()) is True
    assert not any(
        "task 0 " in m.content for m in read_active_messages(ot) if not m.metadata.get("compaction")
    )
    assert "task 0" in summarize_session(ot, "s")  # the audit log is intact


def test_second_compaction_rebuilds_from_the_last_marker_and_carries_the_first(
    tmp_path: Path,
) -> None:
    ot = _ws(tmp_path)
    config = _config()
    _fill(ot, 12)
    assert maybe_compact_session(ot, config) is True
    first = read_messages(ot)[-1]
    _fill(ot, 12, start=100)
    assert maybe_compact_session(ot, config) is True
    raw = read_messages(ot)
    markers = [m for m in raw if m.metadata.get("compaction_marker")]
    assert len(markers) == 2
    active = read_active_messages(ot)
    assert active[0].metadata["compaction_id"] == markers[-1].metadata["compaction_id"]
    assert sum(1 for m in active if m.metadata.get("compaction")) == 1
    assert "Earlier checkpoint (carried forward)" in summary_body(active[0])
    assert summary_body(first).splitlines()[0] in summary_body(active[0])
    assert active[-1].content.startswith("answer 111")


def test_reported_tokens_trigger_where_the_estimate_would_not(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = _config(budget=2000)  # trigger at 1000 estimated tokens
    _fill(ot, 4)  # ~ 4 * 2 * 40 = 320 estimated tokens
    assert maybe_compact_session(ot, config) is False
    assert maybe_compact_session(ot, config, token_scale=1.2) is False
    # The provider counted 4x what chars/4 suggested: the real history is over budget.
    config.context.compaction_keep_ratio = 0.1
    assert maybe_compact_session(ot, config, token_scale=4.0) is True


def test_absolute_prompt_token_trigger_and_force(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = _config(budget=2000)
    config.context.compaction_keep_ratio = 0.1
    _fill(ot, 4)
    assert maybe_compact_session(ot, config, reported_prompt_tokens=150_000) is False
    config.context.compact_at_prompt_tokens = 120_000
    assert maybe_compact_session(ot, config, reported_prompt_tokens=150_000) is True
    assert read_messages(ot)[-1].metadata["trigger"] == "prompt_tokens"


def test_force_compacts_regardless_of_budget(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = _config(budget=1000)
    _fill(ot, 6)
    assert maybe_compact_session(ot, config) is False
    assert maybe_compact_session(ot, config, force=True) is True
    assert read_messages(ot)[-1].metadata["trigger"] == "forced"


def test_llm_summary_is_used_and_a_truncated_one_is_rejected(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = _config()
    config.context.compaction_llm = True
    config.model.provider = "openai"
    _fill(ot, 12)
    cut = ProviderResponse(kind="message", content="- goal: half", truncated=True)
    assert maybe_compact_session(ot, config, provider=ScriptedProvider([cut])) is True
    assert "half" not in read_messages(ot)[-1].metadata["summary"]  # fell back
    _fill(ot, 12, start=50)
    good = ProviderResponse(kind="message", content="- tried X at path a/b.py; failed: Err 7")
    provider = ScriptedProvider([good])
    assert maybe_compact_session(ot, config, provider=provider) is True
    assert read_messages(ot)[-1].metadata["summary"] == "- tried X at path a/b.py; failed: Err 7"
    sent = provider.calls[0][0]
    assert sent[0].content == compaction._LLM_SUMMARY_SYSTEM
    assert "[earlier checkpoint]" in sent[1].content  # the first summary is carried in


def test_agent_loop_calibrates_the_trigger_from_reported_prompt_tokens(tmp_path: Path) -> None:
    from opentorus.agent.loop import AgentLoop
    from opentorus.tools.registry import ToolRegistry

    ot = _ws(tmp_path)
    config = default_config()
    reply = ProviderResponse(
        kind="message", content="done", usage=TokenUsage(prompt_tokens=50_000, completion_tokens=1)
    )
    loop = AgentLoop(tmp_path, ot, ScriptedProvider([reply]), ToolRegistry(), config)
    loop.run("hello")
    assert loop._last_prompt_tokens == 50_000
    assert loop._token_scale is not None and loop._token_scale > 1.0
