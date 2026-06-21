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

from opentorus.agent.session import SessionMessage


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
            if tool_calls:
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
                            for tc in tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": "assistant", "content": message.content})
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
