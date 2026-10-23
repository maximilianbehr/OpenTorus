"""Bound every tool result before it is fed back to the model.

One ``run_shell`` that prints a megabyte, or a ``read_file`` on a generated log, used
to go to the model whole on every later turn until compaction caught up — crowding out
the conversation it belonged to. The bound is applied when the request is assembled,
not when the result is persisted: ``session.jsonl`` and ``actions.jsonl`` keep exactly
what they kept before, so the full output stays inspectable.

The cut is targeted, after the harness reference (``chat-agent`` ``bounded_result``):
the *longest* field is shortened first, so the small fields beside it — a command's
``exit_code=``, ``timed_out``, ``status=`` — still reach the model. A JSON object is cut
on its longest string value; a ``run_shell``-style text (``stdout:`` / ``stderr:``
sections) on its longest section; any other text as one field. The cut keeps the head
and the tail of the field (errors usually sit at the end) and says how much is missing
with an explicit ``[cut: N chars omitted]`` marker. Deterministic by construction.
"""

from __future__ import annotations

import json
import re

from opentorus.agent.session import SessionMessage

DEFAULT_MAX_TOOL_RESULT_CHARS = 64_000

# Headroom for the marker itself and for JSON re-escaping.
_MARKER_RESERVE = 200
_SECTION_HEADER = re.compile(r"^(stdout|stderr|output|log):[ \t]*$", re.MULTILINE)


def _marker(omitted: int) -> str:
    return f"\n[cut: {omitted} chars omitted]\n"


def _cut_middle(text: str, keep: int) -> str:
    """Keep ``keep`` characters of ``text`` — two thirds head, one third tail."""
    if len(text) <= keep:
        return text
    keep = max(0, keep)
    head = (keep * 2) // 3
    tail = keep - head
    omitted = len(text) - head - tail
    return text[:head] + _marker(omitted) + (text[len(text) - tail :] if tail else "")


def _bound_json(text: str, limit: int) -> str | None:
    """Cut the longest string value of a JSON object; ``None`` if ``text`` is not one."""
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    strings = [(k, v) for k, v in data.items() if isinstance(v, str)]
    if not strings:
        return None
    key, value = max(strings, key=lambda kv: len(kv[1]))
    excess = len(text) - limit
    keep = len(value) - excess - _MARKER_RESERVE
    if keep <= 0:
        return None
    data[key] = _cut_middle(value, keep)
    out = json.dumps(data, ensure_ascii=False)
    return out if len(out) <= limit else None


def _bound_sections(text: str, limit: int) -> str | None:
    """Cut the longest ``stdout:``/``stderr:`` section; ``None`` without sections."""
    headers = list(_SECTION_HEADER.finditer(text))
    if not headers:
        return None
    # Spans of each section body (after its header line, up to the next header).
    bodies: list[tuple[int, int]] = []
    for i, match in enumerate(headers):
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        bodies.append((start, end))
    start, end = max(bodies, key=lambda span: span[1] - span[0])
    excess = len(text) - limit
    keep = (end - start) - excess - _MARKER_RESERVE
    if keep <= 0:
        return None
    out = text[:start] + _cut_middle(text[start:end], keep) + text[end:]
    return out if len(out) <= limit else None


def bound_tool_result(text: str, limit: int = DEFAULT_MAX_TOOL_RESULT_CHARS) -> str:
    """Return ``text`` within ``limit`` characters (``limit <= 0`` disables the bound)."""
    if limit <= 0 or len(text) <= limit:
        return text
    for strategy in (_bound_json, _bound_sections):
        bounded = strategy(text, limit)
        if bounded is not None:
            return bounded
    return _cut_middle(text, max(0, limit - _MARKER_RESERVE))


def bound_tool_messages(messages: list[SessionMessage], limit: int) -> list[SessionMessage]:
    """Copy of ``messages`` with every ``tool`` message's content bounded.

    Messages that fit are passed through as the same objects; only an over-long tool
    result is replaced by a copy, so nothing read from disk is mutated.
    """
    if limit <= 0:
        return messages
    out: list[SessionMessage] = []
    for message in messages:
        if message.role == "tool" and len(message.content) > limit:
            bounded = bound_tool_result(message.content, limit)
            message = message.model_copy(
                update={
                    "content": bounded,
                    "metadata": {**message.metadata, "bounded_from_chars": len(message.content)},
                }
            )
        out.append(message)
    return out
