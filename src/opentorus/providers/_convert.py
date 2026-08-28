"""Helpers to translate neutral OpenTorus messages/tools to provider formats.

OpenAI and Ollama share the same chat-message roles (system/user/assistant/tool)
and a similar tool schema, so their conversions live here. Anthropic uses a
different content-block structure and converts inside its own provider.

The neutral representation is a list of :class:`SessionMessage`:
- assistant tool-call turns carry ``metadata['tool_calls'] = [{id, name, args}]``
- tool result turns carry ``metadata['tool_call_id']`` and ``metadata['name']``
"""

from __future__ import annotations

import json
import re

from opentorus.agent.session import SessionMessage

# OpenAI requires tool/function names to match this pattern. A name from another
# provider's output (e.g. a gpt-oss "harmony" channel marker like
# ``assistant<|channel|>commentary`` mis-parsed into a tool call and persisted) would
# otherwise reach the API and be rejected with a 400.
_OPENAI_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _valid_openai_tool_name(name: object) -> bool:
    return isinstance(name, str) and bool(_OPENAI_TOOL_NAME_RE.match(name))


def _user_message_content(message: SessionMessage) -> str | list[dict]:
    """OpenAI/Anthropic multimodal user content when ``images`` are attached."""
    if not message.images:
        return message.content
    blocks: list[dict] = [{"type": "text", "text": message.content}]
    for image in message.images:
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image}"},
            }
        )
    return blocks


def to_openai_messages(messages: list[SessionMessage]) -> list[dict]:
    """Convert to OpenAI chat messages (arguments serialized as JSON strings)."""
    out: list[dict] = []
    for message in messages:
        if message.role == "system":
            out.append({"role": message.role, "content": message.content})
        elif message.role == "user":
            out.append({"role": "user", "content": _user_message_content(message)})
        elif message.role == "assistant":
            tool_calls = message.metadata.get("tool_calls")
            # Drop tool calls whose name is not a valid OpenAI function name (garbage
            # leaked from another provider's output); their orphan tool results are
            # then dropped by the pairing repair below.
            valid_calls = [
                tc for tc in (tool_calls or []) if _valid_openai_tool_name(tc.get("name"))
            ]
            if valid_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": message.content or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc.get("args", {})),
                                },
                            }
                            for tc in valid_calls
                        ],
                    }
                )
            else:
                # No valid tool calls remain → a plain assistant turn (content must be
                # non-empty for OpenAI, so fall back to a marker).
                out.append(
                    {"role": "assistant", "content": message.content or "(tool call omitted)"}
                )
        elif message.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": message.metadata.get("tool_call_id", ""),
                    "content": message.content,
                }
            )
    return _ensure_user_turn(_repair_openai_tool_pairing(_fold_late_system_messages(out)))


_RESUMED_USER_TURN = (
    "[session resumed after context compaction — no live user turn survived; "
    "continue the task described above]"
)


def _ensure_user_turn(out: list[dict]) -> list[dict]:
    """Guarantee the request carries at least one ``user`` message.

    Strict local chat templates (qwen on vLLM) reject a request without one:
    ``400 No user query found in messages``. A compaction can leave exactly that
    shape — the summary is a ``system`` message and the only surviving turn was an
    orphan ``tool`` result, which the pairing repair above rightly drops — so a
    long run died mid-loop on an all-system payload. Appending a neutral user turn
    keeps the request well-formed without disturbing the cacheable prefix.
    """
    if any(m.get("role") == "user" for m in out):
        return out
    return [*out, {"role": "user", "content": _RESUMED_USER_TURN}]


def _append_text(content: str | list[dict], text: str) -> str | list[dict]:
    """Add ``text`` to a user message's content, string or multimodal block list."""
    if isinstance(content, list):
        return [*content, {"type": "text", "text": text}]
    joined = f"{content}\n\n{text}" if content else text
    return joined.strip()


def _fold_late_system_messages(out: list[dict]) -> list[dict]:
    """Fold any ``system`` message past the leading run into a ``user`` turn.

    OpenTorus deliberately places volatile state (workspace inventory, retrieval
    hits) late, so everything ahead of it stays a reusable prefix for a local
    server's KV cache — see ``agent.context`` and ``tests/test_stable_prefix.py``.
    It carries that block as a ``system`` message, which the qwen-family chat
    template rejects outright: vLLM answers ``400 System message must be at the
    beginning`` and the run dies on its first call. Six campaign drivers died that
    way 38 seconds in, against a model that had answered a tool-calling probe
    moments earlier.

    The fix belongs here rather than in the context builder: this is where the wire
    format is produced, the internal message model stays untouched (transcripts and
    the prefix reasoning with it), and *every* late system message is covered, not
    just today's. Folding into an adjacent user turn — rather than emitting a
    standalone ``user`` message — also avoids two same-role messages in a row, which
    is what other strict local templates refuse.
    """
    head = 0
    while head < len(out) and out[head].get("role") == "system":
        head += 1
    # One system message, not a run of them. qwen's template rejects the second one
    # with the same "System message must be at the beginning" — the message means
    # "a system message turned up where none may be", and index 1 is already such a
    # place. A campaign strategist call carried four (system prompt, tool routing,
    # current task, workspace context) and died on its first request. Concatenating
    # preserves the text and the order, and the head stays a stable cache prefix.
    if head > 1:
        merged = "\n\n".join(str(m.get("content") or "") for m in out[:head]).strip()
        out = [{"role": "system", "content": merged}, *out[head:]]
        head = 1
    folded: list[dict] = out[:head]
    pending = ""  # a folded block waiting for the user turn it belongs to
    for message in out[head:]:
        role = message.get("role")
        if role == "system":
            text = message.get("content") or ""
            if folded and folded[-1].get("role") == "user":
                folded[-1] = {**folded[-1], "content": _append_text(folded[-1]["content"], text)}
            else:
                # Nothing to merge into behind us; carry it to the next user turn so
                # the user's own words still end that turn.
                pending = f"{pending}\n\n{text}".strip() if pending else text
            continue
        if role == "user" and pending:
            # Prepend, so the question remains the last thing the model reads.
            folded.append({**message, "content": _prepend_text(message["content"], pending)})
            pending = ""
            continue
        folded.append(message)
    if pending:
        folded.append({"role": "user", "content": pending})
    return folded


def _prepend_text(content: str | list[dict], text: str) -> str | list[dict]:
    if isinstance(content, list):
        return [{"type": "text", "text": text}, *content]
    joined = f"{text}\n\n{content}" if content else text
    return joined.strip()


_INTERRUPTED_TOOL_RESULT = (
    "[no result recorded — the previous run was interrupted before this tool returned]"
)


def _repair_openai_tool_pairing(out: list[dict]) -> list[dict]:
    """Make the message list satisfy OpenAI's strict tool-call/result pairing.

    OpenAI requires every assistant ``tool_calls`` message to be immediately
    followed by one ``tool`` message per ``tool_call_id``. A stopped/resumed run or
    a compaction that split a call from its result can leave a dangling tool call
    (HTTP 400) or an orphan tool result. This repairs both: a missing result gets a
    synthetic placeholder; a stray/orphan ``tool`` message is dropped.
    """
    repaired: list[dict] = []
    i, n = 0, len(out)
    while i < n:
        msg = out[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            repaired.append(msg)
            ids = [tc["id"] for tc in msg["tool_calls"]]
            seen: set[str] = set()
            j = i + 1
            # Consume the immediately-following tool results for these ids, in order.
            while (
                j < n
                and out[j].get("role") == "tool"
                and out[j].get("tool_call_id") in ids
                and out[j].get("tool_call_id") not in seen
            ):
                repaired.append(out[j])
                seen.add(out[j]["tool_call_id"])
                j += 1
            for call_id in ids:
                if call_id not in seen:
                    repaired.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": _INTERRUPTED_TOOL_RESULT,
                        }
                    )
            i = j
        elif msg.get("role") == "tool":
            # A tool message not consumed above is orphaned/misplaced — drop it
            # (a valid one was already paired with its assistant tool_calls).
            i += 1
        else:
            repaired.append(msg)
            i += 1
    return repaired


def to_ollama_messages(messages: list[SessionMessage]) -> list[dict]:
    """Convert to Ollama chat messages (arguments kept as JSON objects)."""
    out: list[dict] = []
    for message in messages:
        if message.role == "system":
            out.append({"role": message.role, "content": message.content})
        elif message.role == "user":
            entry: dict = {"role": "user", "content": message.content}
            if message.images:
                entry["images"] = message.images
            out.append(entry)
        elif message.role == "assistant":
            tool_calls = message.metadata.get("tool_calls")
            if tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {"function": {"name": tc["name"], "arguments": tc.get("args", {})}}
                            for tc in tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": "assistant", "content": message.content})
        elif message.role == "tool":
            entry = {"role": "tool", "content": message.content}
            name = message.metadata.get("name")
            if name:
                entry["tool_name"] = name
            out.append(entry)
    return _merge_leading_system(_fold_stray_system(out))


def _merge_leading_system(messages: list[dict]) -> list[dict]:
    """Collapse the leading run of system messages into exactly one.

    OpenTorus builds several leading system blocks (workspace context, task goal,
    retrieval, …). Strict chat templates accept only a single system message and
    reject the rest with the *misleading* error "system message must be at the
    beginning" — verified against Ollama: one leading system works, two do not,
    regardless of position. That made whole model families (e.g. qwen3.8) fail on
    their first turn with zero tool calls. Merging preserves the content verbatim
    and every template accepts the result.
    """
    lead = 0
    while lead < len(messages) and messages[lead].get("role") == "system":
        lead += 1
    if lead <= 1:
        return messages
    merged = {
        "role": "system",
        "content": "\n\n".join(m.get("content") or "" for m in messages[:lead]).strip(),
    }
    return [merged, *messages[lead:]]


def _fold_stray_system(messages: list[dict]) -> list[dict]:
    """Fold every system message that is not in the leading run into its neighbour.

    The stable-prefix ordering deliberately puts the volatile workspace state in a
    ``system`` message just before the final turn, so the reusable prefix ends as late
    as possible. Strict local chat templates reject that outright — and here the error
    "system message must be at the beginning" means exactly what it says, unlike the
    leading-run case that `_merge_leading_system` handles. Observed as HTTP 500 on
    qwen3.8 and qwen3-coder about ninety seconds into a run, with nothing produced.

    Folding keeps the text where it was — attached to the following user turn, or to the
    preceding tool result when the next turn is a tool_calls group that must not be split
    — so recency, prefix stability and pairing all survive. Only the Ollama payload is
    reshaped; every other provider still sees the message list as built.
    """
    lead = 0
    while lead < len(messages) and messages[lead].get("role") == "system":
        lead += 1
    if not any(m.get("role") == "system" for m in messages[lead:]):
        return messages

    rest = messages[lead:]
    folded = list(messages[:lead])
    for index, message in enumerate(rest):
        if message.get("role") != "system":
            folded.append(message)
            continue
        block = (message.get("content") or "").strip()
        if not block:
            continue
        following = rest[index + 1] if index + 1 < len(rest) else None
        if following is not None and following.get("role") == "user":
            # Preferred home: the turn it was meant to inform. _merge_adjacent_users
            # below collapses the two into one user message.
            folded.append({"role": "user", "content": block})
        elif folded and folded[-1].get("role") == "tool":
            # The next turn is a tool_calls group (or the list ends here) — a user
            # message would split the call from its results, so attach it to the last
            # result instead, which also keeps that result the message being answered.
            folded[-1] = {
                **folded[-1],
                "content": f"{folded[-1].get('content') or ''}\n\n---\n{block}",
            }
        else:
            folded.append({"role": "user", "content": block})
    return _merge_adjacent_users(folded)


def _merge_adjacent_users(messages: list[dict]) -> list[dict]:
    """Collapse consecutive user messages — a run of one role breaks strict templates."""
    out: list[dict] = []
    for message in messages:
        if out and out[-1].get("role") == "user" and message.get("role") == "user":
            out[-1] = {
                **out[-1],
                "content": f"{out[-1].get('content') or ''}\n\n{message.get('content') or ''}",
            }
            continue
        out.append(message)
    return out


def to_function_tools(specs: list[dict]) -> list[dict]:
    """Wrap neutral tool specs as OpenAI/Ollama ``function`` tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description", ""),
                "parameters": spec.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for spec in specs
    ]
