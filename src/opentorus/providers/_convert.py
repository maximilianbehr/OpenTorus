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
    return out


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
