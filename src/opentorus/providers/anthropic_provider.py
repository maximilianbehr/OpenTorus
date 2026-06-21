"""Anthropic provider with tool calling.

Imports the SDK lazily and fails with an actionable message when the package or
API key is missing. Anthropic uses content blocks (``tool_use`` / ``tool_result``)
rather than OpenAI-style tool messages, so it has its own message conversion.
"""

from __future__ import annotations

import os

from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.errors import ProviderError
from opentorus.providers.base import (
    BaseProvider,
    ProviderResponse,
    TokenUsage,
    ToolCallRequest,
    apportion_thinking,
)

# Fallback output-token cap when the model config does not set one. 1024 was too
# low for long proofs/tool arguments; this is configurable via model.max_tokens.
_DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, config: Config) -> None:
        self.config = config

    def generate(
        self, messages: list[SessionMessage], tools: list[dict] | None = None
    ) -> ProviderResponse:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Put it in a .env file in your project "
                "(ANTHROPIC_API_KEY=sk-ant-…) or export it to use the Anthropic provider."
            )
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError(
                "The 'anthropic' package is not installed. Install it with: pip install anthropic"
            ) from exc

        system, convo = to_anthropic_messages(messages)
        kwargs: dict = {
            "model": self.config.model.name,
            "max_tokens": self.config.model.max_tokens or _DEFAULT_MAX_TOKENS,
            "temperature": self.config.model.temperature,
            "system": system,
            "messages": convo,
        }
        if tools:
            kwargs["tools"] = to_anthropic_tools(tools)

        timeout = self.config.model.timeout_seconds
        client = anthropic.Anthropic(timeout=timeout) if timeout else anthropic.Anthropic()
        message = client.messages.create(**kwargs)
        return parse_anthropic_message(message)


def to_anthropic_tools(specs: list[dict]) -> list[dict]:
    return [
        {
            "name": spec["name"],
            "description": spec.get("description", ""),
            "input_schema": spec.get("parameters", {"type": "object", "properties": {}}),
        }
        for spec in specs
    ]


def to_anthropic_messages(messages: list[SessionMessage]) -> tuple[str, list[dict]]:
    """Return (system_text, conversation) in Anthropic's content-block format."""
    system = "\n".join(m.content for m in messages if m.role == "system")
    convo: list[dict] = []
    # The Anthropic API requires that all ``tool_result`` blocks answering one
    # assistant turn's ``tool_use`` calls live in a *single* user message. With
    # parallel tool calls a turn yields several consecutive ``role="tool"``
    # messages, so we coalesce a run of them into one user message instead of
    # emitting one user turn per result (which the API rejects).
    pending_tool_results: list[dict] | None = None
    for message in messages:
        if message.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.metadata.get("tool_call_id", ""),
                "content": message.content,
            }
            if pending_tool_results is None:
                pending_tool_results = [block]
                convo.append({"role": "user", "content": pending_tool_results})
            else:
                pending_tool_results.append(block)
            continue
        # Any non-tool message ends the current run of tool results.
        pending_tool_results = None
        if message.role == "user":
            if message.images:
                blocks: list[dict] = [{"type": "text", "text": message.content}]
                for image in message.images:
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image,
                            },
                        }
                    )
                convo.append({"role": "user", "content": blocks})
            else:
                convo.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            tool_calls = message.metadata.get("tool_calls")
            if tool_calls:
                blocks = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for tc in tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc.get("args", {}),
                        }
                    )
                convo.append({"role": "assistant", "content": blocks})
            else:
                convo.append({"role": "assistant", "content": message.content})
    return system, convo


def _anthropic_usage(message: object) -> TokenUsage | None:
    """Exact token counts from an Anthropic message's ``usage``, or None."""
    usage = getattr(message, "usage", None)
    if usage is None:
        return None
    return TokenUsage(
        prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def parse_anthropic_message(message: object) -> ProviderResponse:
    usage = _anthropic_usage(message)
    truncated = getattr(message, "stop_reason", None) == "max_tokens"
    blocks = getattr(message, "content", []) or []
    # Extended-thinking blocks are billed within ``output_tokens``; Anthropic does
    # not break them out, so apportion the exact total by character share.
    if usage is not None:
        thinking_text = "".join(
            getattr(b, "thinking", "") for b in blocks if getattr(b, "type", "") == "thinking"
        )
        if thinking_text:
            other_text = "".join(
                getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text"
            )
            usage.thinking_tokens = apportion_thinking(
                usage.completion_tokens, thinking_text, other_text
            )
    tool_uses = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
    if tool_uses:
        parsed = [
            ToolCallRequest(
                tool_name=getattr(b, "name", ""),
                tool_args=dict(getattr(b, "input", {}) or {}),
                tool_call_id=getattr(b, "id", None),
            )
            for b in tool_uses
        ]
        first = parsed[0]
        return ProviderResponse(
            kind="tool_call",
            tool_name=first.tool_name,
            tool_args=first.tool_args,
            tool_call_id=first.tool_call_id,
            tool_calls=parsed,
            usage=usage,
            truncated=truncated,
        )
    text = "".join(
        getattr(block, "text", "") for block in blocks if getattr(block, "type", "") == "text"
    )
    return ProviderResponse(kind="message", content=text, usage=usage, truncated=truncated)
