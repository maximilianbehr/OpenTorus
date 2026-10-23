"""Token-budget-aware history compaction.

When a session grows past the configured token budget, older conversation turns
are summarized into a single inspectable system message so the thread is kept
without blowing the context window. The summary preserves goals, tools used, and
key responses, and is persisted under ``.opentorus/compaction/`` as an audit
artifact. Leading system messages (system prompt, context, selected artifacts)
are always kept verbatim.

When ``compaction_threshold`` is exceeded, ``maybe_compact_session`` appends a
compaction *marker* to ``.opentorus/session.jsonl`` (never rewriting it); the history
the model sees is rebuilt from the last marker (``read_active_messages``), while the
file itself stays the complete audit log. The trigger uses the provider-reported
prompt tokens when they are known, the chars/4 estimate otherwise.

Every summary opens with a resume prefix: it is a record of work already done in the
same workspace, files on disk are as they were left, check before rebuilding, and do
not repeat what the summary says failed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from opentorus.agent.session import SessionMessage, append_message, read_messages
from opentorus.config import Config
from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl

if TYPE_CHECKING:
    from opentorus.providers.base import BaseProvider

logger = logging.getLogger("opentorus")

# Rough, provider-agnostic estimate: ~4 characters per token.
_CHARS_PER_TOKEN = 4

_COMPACTION_SUMMARY_PREFIX = (
    "Summary of earlier conversation (compacted to stay within the token budget):"
)

# A failed attempt is only useful if the model can tell *what* went wrong, so keep
# enough of the error to be actionable — but a compaction summary that reproduces
# whole tracebacks defeats its own purpose.
_FAILURE_DETAIL_CHARS = 220
_MAX_FAILURES_KEPT = 12

# The checkpoint prompt, after the harness reference (prompts/templates/compact/prompt.md):
# the summary REPLACES the turns it covers, so it is written for a reader who has none of
# them — and the part most often left out (what failed, and why) is the part that saves
# the most time.
_LLM_SUMMARY_SYSTEM = """\
You are writing a CONTEXT CHECKPOINT for a research engineering agent. The conversation \
turns below are about to be replaced by what you write; another model — possibly you, with \
none of this in memory — will pick the work up from it.

Write for that reader. Include:
- The user's goals and constraints, in their words where the wording matters.
- What has been established, and what is still only a guess (evidence is not proof; keep \
claim/evidence statuses exactly as recorded).
- The decisions taken and the reason for each, so they are not re-litigated.
- What was tried and did NOT work, and why it did not. This is the part that saves the \
most time and the part most often left out.
- The current state: which files were written or changed, which experiments ran, what is \
in progress.
- What remains, as concrete next steps rather than as a topic.
- Every identifier the next reader cannot rediscover, copied EXACTLY: file paths, artifact \
ids (PAPER-*, CLAIM-*, EXP-*, PROBLEM-*), commands, measured numbers, parameter values, and \
the exact text of error messages that matter.

Be specific over complete: "explored several approaches" throws the work away; naming \
each approach and what killed it keeps it. Omit repeated tool noise and long raw outputs. \
Do not invent facts; if something is unknown, say so. Plain text or bullet points.\
"""

# Placed in front of every compaction summary (LLM or heuristic), after the harness
# reference (prompts/templates/compact/summary_prefix.md): the next model must read the
# summary as a record of work already done in the SAME workspace — not as a proposal,
# and not as a fresh start.
_RESUME_PREFIX = (
    "This summary is a record of what was already done earlier in this same piece of "
    "work, not a proposal. Everything outside the conversation is exactly as it was "
    "left: files written are on disk, artifacts under .opentorus/ are recorded, and "
    "anything started is where it was put. Check the current state before you rebuild "
    "something that may already exist, and do not repeat an approach the summary says "
    "was tried and failed."
)

# How much of one message the summarizer sees. Exact identifiers and error text live in
# these bodies; cutting them at 600 characters lost exactly what the summary must keep.
_TRANSCRIPT_MESSAGE_CHARS = 2000
_TRANSCRIPT_TOOL_CHARS = 1500


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


def summary_body(message: SessionMessage) -> str:
    """The summary text of a compaction message, without its headers."""
    body = message.metadata.get("summary")
    if isinstance(body, str) and body.strip():
        return body.strip()
    text = message.content
    if text.startswith(_COMPACTION_SUMMARY_PREFIX):
        text = text[len(_COMPACTION_SUMMARY_PREFIX) :]
    text = text.strip()
    if text.startswith(_RESUME_PREFIX):
        text = text[len(_RESUME_PREFIX) :]
    return text.strip()


def _bounded_body(body: str, config: Config) -> str:
    limit = int(getattr(config.context, "compaction_summary_max_chars", 12_000) or 0)
    body = body.strip()
    if limit > 0 and len(body) > limit:
        body = body[:limit].rstrip() + f"\n[cut: {len(body) - limit} chars omitted]"
    return body


def summary_text(body: str) -> str:
    """The full summary message: detection prefix, resume prefix, then the body."""
    return f"{_COMPACTION_SUMMARY_PREFIX}\n{_RESUME_PREFIX}\n\n{body.strip()}"


def _format_turns_for_llm(messages: list[SessionMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        if _is_compaction_summary(message):
            # An earlier checkpoint is carried forward whole: it is the only record left
            # of the turns it replaced.
            lines.append(f"[earlier checkpoint]\n{summary_body(message)}")
            continue
        role = message.role.upper()
        text = " ".join(message.content.split())
        cap = _TRANSCRIPT_TOOL_CHARS if message.role == "tool" else _TRANSCRIPT_MESSAGE_CHARS
        if len(text) > cap:
            text = text[: cap - 1] + "…"
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


def _failed_attempts(messages: list[SessionMessage]) -> list[str]:
    """Failed tool calls in a compacted window, kept with their error text.

    "Failed attempts are first-class" is one of the project's invariants, and both the
    loop and the prove loop tell the user in so many words that a failing call and its
    error "are preserved in the session log". The log now keeps them (compaction is
    append-only), but the *model* only sees the summary of a compacted window, so
    without this a dead end survived as the bare word ``proof_write`` in a list of
    tool names, and the agent was free to walk into it again.
    """
    out: list[str] = []
    for message in messages:
        if message.role != "tool" or message.metadata.get("ok", True):
            continue
        name = str(message.metadata.get("name", "tool"))
        error = " ".join(message.content.split())
        out.append(f"{name} → {error[:_FAILURE_DETAIL_CHARS]}")
    # Same tool, same error, many times over is one dead end, not twenty.
    return list(dict.fromkeys(out))


def _summarize_turns(messages: list[SessionMessage]) -> str:
    goals = [
        m.content
        for m in messages
        if m.role == "user" and m.content.strip() and not m.metadata.get("synthetic")
    ]
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

    lines: list[str] = []
    earlier = [summary_body(m) for m in messages if _is_compaction_summary(m)]
    if earlier:
        lines.append("- Earlier checkpoint (carried forward):\n" + earlier[-1])
    if goals:
        lines.append("- Goals: " + "; ".join(g[:120] for g in goals))
    if tools:
        lines.append("- Tools used: " + ", ".join(dict.fromkeys(tools)))
    if responses:
        lines.append("- Key responses: " + " | ".join(r[:400] for r in responses[-3:]))
    unrun = [
        f"{m.metadata.get('name', 'tool')} ({str(m.metadata['unrun']).replace('_', ' ')})"
        for m in messages
        if m.role == "tool" and m.metadata.get("unrun")
    ]
    if unrun:
        lines.append("- Calls that did not complete: " + ", ".join(dict.fromkeys(unrun)))
    failures = _failed_attempts(messages)
    if failures:
        lines.append(
            "- Failed attempts (do NOT repeat these; they are recorded, not undone):\n  - "
            + "\n  - ".join(failures[:_MAX_FAILURES_KEPT])
        )
        if len(failures) > _MAX_FAILURES_KEPT:
            lines.append(
                f"  - …and {len(failures) - _MAX_FAILURES_KEPT} further distinct failures "
                "(see .opentorus/actions.jsonl)."
            )
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
            content="Write the context checkpoint for these turns:\n\n" + transcript,
        ),
    ]
    try:
        response = provider.respond(prompt_messages, tools=None)
    except Exception as exc:  # noqa: BLE001 — compaction must never abort the agent loop
        logger.debug("LLM compaction summary failed: %s", exc)
        return None
    if response.kind != "message" or not response.content.strip():
        return None
    if response.truncated:
        # A summary cut off at the output limit has lost its tail — usually the
        # "what remains" part. Fall back to the deterministic summary instead.
        logger.debug("LLM compaction summary was truncated; using the heuristic summary.")
        return None
    return response.content.strip()


def _record(ot_dir: Path, summarized: int, summary: str) -> str:
    compaction_dir(ot_dir).mkdir(parents=True, exist_ok=True)
    path = _history_path(ot_dir)
    record = CompactionRecord(
        id=next_sequential_id("COMPACT", len(read_jsonl(path, CompactionRecord))),
        summarized_messages=summarized,
        summary=summary,
    )
    append_jsonl(path, record)
    return record.id


def _split_recent(
    messages: list[SessionMessage], keep_budget: int, scale: float = 1.0
) -> tuple[list[SessionMessage], list[SessionMessage]]:
    kept: list[SessionMessage] = []
    used = 0.0
    for message in reversed(messages):
        cost = estimate_tokens(message.content) * scale
        if kept and used + cost > keep_budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    older = messages[: len(messages) - len(kept)]
    return older, kept


def _summarize(
    older: list[SessionMessage], config: Config, provider: BaseProvider | None
) -> str | None:
    """Summary body for ``older`` (LLM first, deterministic fallback), or None.

    Earlier checkpoints inside ``older`` are carried into the new summary rather than
    dropped: they are the only record left of the turns they replaced. ``None`` when
    ``older`` holds nothing but earlier checkpoints — there is nothing new to fold in.
    """
    if not [m for m in older if not _is_compaction_summary(m)]:
        return None
    body = _llm_summarize(provider, older, config) if provider is not None else None
    if body is None:
        body = _summarize_turns(older)
    return _bounded_body(body, config)


# --- the session-level, append-only compaction ----------------------------------------------
#
# ``session.jsonl`` used to be REWRITTEN when it outgrew the budget: the summarized turns
# were deleted from disk, so a long run's own audit log lost its beginning (and "failed
# attempts are preserved" stopped being true the moment a run compacted). The log is now
# append-only. A compaction appends one *marker* record — a system message carrying the
# summary — and the model-facing history is rebuilt from the LAST marker: the marker,
# then the turns it kept verbatim (``keep_from`` is the raw-file index of the first one),
# then everything appended after it. A session without markers (every session written
# before this change, including ones an old version rewrote) reads exactly as before.


def is_compaction_marker(message: SessionMessage) -> bool:
    return bool(message.metadata.get("compaction_marker"))


def _active_indexed(messages: list[SessionMessage]) -> list[tuple[int, SessionMessage]]:
    """The model-facing view of a raw session log, with each message's raw index."""
    last = None
    for index in range(len(messages) - 1, -1, -1):
        if is_compaction_marker(messages[index]):
            last = index
            break
    if last is None:
        return list(enumerate(messages))
    marker = messages[last]
    try:
        keep_from = int(marker.metadata.get("keep_from", last))
    except (TypeError, ValueError):
        keep_from = last
    keep_from = min(max(0, keep_from), last)
    kept = [
        (i, messages[i]) for i in range(keep_from, last) if not is_compaction_marker(messages[i])
    ]
    tail = list(enumerate(messages))[last + 1 :]
    return [(last, marker), *kept, *tail]


def active_messages(messages: list[SessionMessage]) -> list[SessionMessage]:
    """Rebuild the model-facing history from the last compaction marker (if any)."""
    return [m for _, m in _active_indexed(messages)]


def read_active_messages(ot_dir: Path) -> list[SessionMessage]:
    """``session.jsonl`` as the model sees it: from the last compaction marker on.

    ``read_messages`` stays the full, append-only audit log (replay, bundles, harvest).
    """
    return active_messages(read_messages(ot_dir))


def _token_scale(scale: float | None) -> float:
    """Clamp a provider-calibrated tokens-per-estimated-token factor to a sane range."""
    if scale is None or scale <= 0:
        return 1.0
    return min(4.0, max(0.5, float(scale)))


def maybe_compact_session(
    ot_dir: Path,
    config: Config,
    *,
    provider: BaseProvider | None = None,
    reported_prompt_tokens: int | None = None,
    token_scale: float | None = None,
    force: bool = False,
) -> bool:
    """Compact the session history by appending a marker once it is over budget.

    The trigger is the history's size against ``token_budget * compaction_threshold``,
    measured in *real* tokens when the provider reported them: ``token_scale`` is the
    previous request's reported ``prompt_tokens`` divided by the local estimate of that
    same request, so the chars/4 estimate is corrected by what the provider actually
    counted (math and code run closer to 3 chars per token). ``context.
    compact_at_prompt_tokens``, when set, also triggers on the reported prompt size
    itself. ``force`` compacts regardless — the provider said the context is full.
    Never rewrites ``session.jsonl``; returns True when a marker was appended.
    """
    if not config.context.compaction_enabled:
        return False
    raw = read_messages(ot_dir)
    if not raw:
        return False
    indexed = _active_indexed(raw)
    active = [m for _, m in indexed]
    scale = _token_scale(token_scale)
    trigger = int(config.context.token_budget * config.context.compaction_threshold)
    hard_limit = getattr(config.context, "compact_at_prompt_tokens", None)
    over_hard = bool(hard_limit) and (reported_prompt_tokens or 0) >= int(hard_limit or 0)
    if not force and not over_hard and total_tokens(active) * scale <= trigger:
        return False

    keep_budget = max(200, int(config.context.token_budget * config.context.compaction_keep_ratio))
    if force or over_hard:
        # The provider said the context is (nearly) full: keep a smaller recent window —
        # at most half of what is there now, whatever the configured budget says (an
        # overflow means the configured budget did not fit this model).
        current = int(total_tokens(active) * scale)
        keep_budget = max(200, min(keep_budget // 2, current // 2))
    older, kept = _split_recent(active, keep_budget, scale)
    if not older:
        return False
    body = _summarize(older, config, provider)
    if body is None:
        return False
    content = summary_text(body)
    compaction_id = _record(ot_dir, len(older), content)
    # Raw index of the first message kept verbatim (or "nothing kept": the marker's own
    # index, which is the current end of the file).
    keep_from = indexed[len(older)][0] if kept else len(raw)
    if kept and is_compaction_marker(kept[0]):
        keep_from = len(raw)
    append_message(
        ot_dir,
        SessionMessage(
            role="system",
            content=content,
            metadata={
                "compaction": True,
                "compaction_marker": True,
                "compaction_id": compaction_id,
                "keep_from": keep_from,
                "summarized_messages": len(older),
                "summary": body,
                "trigger": "forced" if force else ("prompt_tokens" if over_hard else "budget"),
            },
        ),
    )
    return True


def compact_messages(
    ot_dir: Path,
    messages: list[SessionMessage],
    config: Config,
    *,
    provider: BaseProvider | None = None,
    token_scale: float | None = None,
) -> list[SessionMessage]:
    """Compact older turns of one assembled request into a summary when over budget.

    This is the per-request safety net (nothing is persisted to ``session.jsonl``; the
    summary is recorded under ``.opentorus/compaction/``).
    """
    if not config.context.compaction_enabled:
        return messages
    scale = _token_scale(token_scale)
    if total_tokens(messages) * scale <= config.context.token_budget:
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
    # Floor the recent-conversation budget: a large rebuilt system head (the full
    # artifact inventory each turn) must not starve recent turns down to nothing.
    # Reserve ``compaction_keep_ratio`` of the token budget for recent turns (scaled to
    # the budget, not an absolute floor that would suppress compaction at small budgets),
    # even if that means the head + summary slightly overflow.
    recent_floor = int(config.context.token_budget * config.context.compaction_keep_ratio)
    budget = max(recent_floor, int(config.context.token_budget - total_tokens(head) * scale))

    older, kept = _split_recent(convo, budget, scale)
    if not older:
        return messages
    body = _summarize(older, config, provider)
    if body is None:
        return messages
    content = summary_text(body)
    _record(ot_dir, len(older), content)
    summary_message = SessionMessage(
        role="system", content=content, metadata={"compaction": True, "summary": body}
    )
    return head + [summary_message] + kept
