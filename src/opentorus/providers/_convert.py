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
    return _repair_openai_tool_pairing(out)


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
