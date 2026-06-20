"""Token-budget-aware history compaction.

When a session grows past the configured token budget, older conversation turns
are summarized into a single inspectable system message so the thread is kept
without blowing the context window. The summary preserves goals, tools used, and
key responses, and is persisted under ``.opentorus/compaction/`` as an audit
artifact. Leading system messages (system prompt, context, selected artifacts)
are always kept verbatim.

When ``compaction_threshold`` is exceeded, ``maybe_compact_session`` also rewrites
``.opentorus/session.jsonl`` so on-disk history stays bounded across long runs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from opentorus.agent.session import SessionMessage, read_messages, session_path
from opentorus.config import Config
from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl, rewrite_jsonl

if TYPE_CHECKING:
    from opentorus.providers.base import BaseProvider

logger = logging.getLogger("opentorus")

# Rough, provider-agnostic estimate: ~4 characters per token.
_CHARS_PER_TOKEN = 4

_COMPACTION_SUMMARY_PREFIX = (
    "Summary of earlier conversation (compacted to stay within the token budget):"
)

_LLM_SUMMARY_SYSTEM = """\
You compact conversation history for a research engineering agent.
Preserve: user goals, decisions, artifact IDs (PAPER-*, CLAIM-*, PROBLEM-*),
tools used, key results, open gaps, and failures.
Omit: repeated tool noise, long raw outputs, and sensitive content markers.
Write concise bullet points under 400 words. Do not invent facts.\
"""


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def total_tokens(messages: list[SessionMessage]) -> int:
    return sum(estimate_tokens(m.content) for m in messages)


class CompactionRecord(BaseModel):
    id: str
    summarized_messages: int
    summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def compaction_dir(ot_dir: Path) -> Path:
    return ot_dir / "compaction"


def _history_path(ot_dir: Path) -> Path:
    return compaction_dir(ot_dir) / "history.jsonl"


def _is_compaction_summary(message: SessionMessage) -> bool:
    return bool(message.metadata.get("compaction")) or message.content.startswith(
        _COMPACTION_SUMMARY_PREFIX
    )


def _format_turns_for_llm(messages: list[SessionMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        if _is_compaction_summary(message):
            lines.append(f"[compacted earlier]\n{message.content[:800]}")
            continue
        role = message.role.upper()
        text = " ".join(message.content.split())
        if len(text) > 600:
            text = text[:597] + "…"
        if message.metadata.get("tool_calls"):
            names = [
                tc.get("name", "?")
                for tc in message.metadata.get("tool_calls", [])
                if tc.get("name")
            ]
            lines.append(f"{role} (tools: {', '.join(names)}): {text}")
        elif message.role == "tool":
            name = message.metadata.get("name", "tool")
            lines.append(f"TOOL {name}: {text}")
        else:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _summarize_turns(messages: list[SessionMessage]) -> str:
    goals = [m.content for m in messages if m.role == "user" and m.content.strip()]
    tools: list[str] = []
    for m in messages:
        for tc in m.metadata.get("tool_calls", []):
            name = tc.get("name")
            if name:
                tools.append(name)
        if m.role == "tool" and m.metadata.get("name"):
            tools.append(str(m.metadata["name"]))
    responses = [
        m.content
        for m in messages
        if m.role == "assistant" and not m.metadata.get("tool_calls") and m.content.strip()
    ]

    lines = [_COMPACTION_SUMMARY_PREFIX]
    if goals:
        lines.append("- Goals: " + "; ".join(g[:120] for g in goals))
    if tools:
        lines.append("- Tools used: " + ", ".join(dict.fromkeys(tools)))
    if responses:
        lines.append("- Key responses: " + " | ".join(r[:160] for r in responses[-3:]))
    return "\n".join(lines)


def _llm_summarize(
    provider: BaseProvider, messages: list[SessionMessage], config: Config
) -> str | None:
    if not config.context.compaction_llm:
        return None
    if config.model.provider == "mock":
        return None
    transcript = _format_turns_for_llm(messages)
    if not transcript.strip():
        return None
    prompt_messages = [
        SessionMessage(role="system", content=_LLM_SUMMARY_SYSTEM),
        SessionMessage(
            role="user",
            content="Summarize this conversation history:\n\n" + transcript,
        ),
    ]
    try:
        response = provider.respond(prompt_messages, tools=None)
    except Exception as exc:  # noqa: BLE001 — compaction must never abort the agent loop
        logger.debug("LLM compaction summary failed: %s", exc)
        return None
    if response.kind != "message" or not response.content.strip():
        return None
    return f"{_COMPACTION_SUMMARY_PREFIX}\n{response.content.strip()}"


def _record(ot_dir: Path, summarized: int, summary: str) -> None:
    compaction_dir(ot_dir).mkdir(parents=True, exist_ok=True)
    path = _history_path(ot_dir)
    record = CompactionRecord(
        id=next_sequential_id("COMPACT", len(read_jsonl(path, CompactionRecord))),
        summarized_messages=summarized,
        summary=summary,
    )
    append_jsonl(path, record)


def _split_recent(
    messages: list[SessionMessage], keep_budget: int
) -> tuple[list[SessionMessage], list[SessionMessage]]:
    kept: list[SessionMessage] = []
    used = 0
    for message in reversed(messages):
        cost = estimate_tokens(message.content)
        if kept and used + cost > keep_budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    older = messages[: len(messages) - len(kept)]
    return older, kept


def _compact_message_list(
    ot_dir: Path,
    messages: list[SessionMessage],
    config: Config,
    *,
    provider: BaseProvider | None = None,
    keep_budget: int | None = None,
) -> list[SessionMessage] | None:
    """Return compacted messages, or None when nothing could be removed."""
    if keep_budget is None:
        keep_budget = max(
            200, int(config.context.token_budget * config.context.compaction_keep_ratio)
        )

    head: list[SessionMessage] = []
    i = 0
    while (
        i < len(messages)
        and messages[i].role == "system"
        and not _is_compaction_summary(messages[i])
    ):
        head.append(messages[i])
        i += 1
    convo = messages[i:]
    if not convo:
        return None

    budget = keep_budget
    older, kept = _split_recent(convo, budget)
    if not older:
        return None

    older = [m for m in older if not _is_compaction_summary(m)]
    if not older:
        return None

    summary = _llm_summarize(provider, older, config) if provider is not None else None
    if summary is None:
        summary = _summarize_turns(older)
    _record(ot_dir, len(older), summary)
    summary_message = SessionMessage(
        role="system",
        content=summary,
        metadata={"compaction": True},
    )
    return head + [summary_message] + kept


def maybe_compact_session(
    ot_dir: Path,
    config: Config,
    *,
    provider: BaseProvider | None = None,
) -> bool:
    """Persistently compact ``session.jsonl`` when it exceeds ``compaction_threshold``."""
    if not config.context.compaction_enabled:
        return False
    messages = read_messages(ot_dir)
    if not messages:
        return False
    trigger = int(config.context.token_budget * config.context.compaction_threshold)
    if total_tokens(messages) <= trigger:
        return False

    keep_budget = max(200, int(config.context.token_budget * config.context.compaction_keep_ratio))
    compacted = _compact_message_list(
        ot_dir, messages, config, provider=provider, keep_budget=keep_budget
    )
    if compacted is None:
        return False
    rewrite_jsonl(session_path(ot_dir), compacted)
    return True


def compact_messages(
    ot_dir: Path,
    messages: list[SessionMessage],
    config: Config,
    *,
    provider: BaseProvider | None = None,
) -> list[SessionMessage]:
    """Compact older turns into a summary when over the token budget."""
    if not config.context.compaction_enabled:
        return messages
    if total_tokens(messages) <= config.context.token_budget:
        return messages

    head: list[SessionMessage] = []
    i = 0
    while (
        i < len(messages)
        and messages[i].role == "system"
        and not _is_compaction_summary(messages[i])
    ):
        head.append(messages[i])
        i += 1
    convo = messages[i:]
    budget = config.context.token_budget - total_tokens(head)

    older, kept = _split_recent(convo, budget)
    if not older:
        return messages

    older = [m for m in older if not _is_compaction_summary(m)]
    if not older:
        return messages

    summary = _llm_summarize(provider, older, config) if provider is not None else None
    if summary is None:
        summary = _summarize_turns(older)
    _record(ot_dir, len(older), summary)
    summary_message = SessionMessage(role="system", content=summary, metadata={"compaction": True})
    return head + [summary_message] + kept
