"""OpenAI provider with tool calling.

Imports the SDK lazily and fails with an actionable message when the package or
API key is missing. Sends tools as OpenAI ``function`` tools and parses
``tool_calls`` back into a :class:`ProviderResponse`.
"""

from __future__ import annotations

import json
import os

from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.errors import ProviderError
from opentorus.providers._convert import to_function_tools, to_openai_messages
from opentorus.providers.base import (
    BaseProvider,
    ProviderResponse,
    TokenUsage,
    ToolCallRequest,
)


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, config: Config) -> None:
        self.config = config

    def generate(
        self, messages: list[SessionMessage], tools: list[dict] | None = None
    ) -> ProviderResponse:
        if not os.environ.get("OPENAI_API_KEY"):
            raise ProviderError(
                "OPENAI_API_KEY is not set. Put it in a .env file in your project "
                "(OPENAI_API_KEY=sk-…) or export it to use the OpenAI provider."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(
                "The 'openai' package is not installed. Install it with: pip install openai"
            ) from exc

        kwargs: dict = {
            "model": self.config.model.name,
            "temperature": self.config.model.temperature,
            "messages": to_openai_messages(messages),
        }
        if tools:
            kwargs["tools"] = to_function_tools(tools)

        client = OpenAI()
        completion = client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        response = parse_openai_message(choice.message)
        response.usage = _openai_usage(completion)
        # finish_reason "length" means the output hit the token ceiling (truncated).
        response.truncated = getattr(choice, "finish_reason", None) == "length"
        return response


def _openai_usage(completion: object) -> TokenUsage | None:
    """Exact token counts from an OpenAI completion's ``usage``, or None.

    Reasoning models report a ``reasoning_tokens`` breakdown inside
    ``completion_tokens_details``; it is already part of ``completion_tokens``.
    """
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "completion_tokens_details", None)
    thinking = int(getattr(details, "reasoning_tokens", 0) or 0) if details is not None else 0
    return TokenUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        thinking_tokens=thinking,
    )


def parse_openai_message(message: object) -> ProviderResponse:
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        parsed: list[ToolCallRequest] = []
        for call in tool_calls:
            raw_args = call.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                # Surface as a recoverable tool-parse error so the loop retries with a
                # correction hint instead of silently calling the tool with no args.
                raise ProviderError(
                    f"Failed to parse JSON tool-call arguments for '{call.function.name}': {exc}."
                ) from exc
            parsed.append(
                ToolCallRequest(tool_name=call.function.name, tool_args=args, tool_call_id=call.id)
            )
        first = parsed[0]
        return ProviderResponse(
            kind="tool_call",
            tool_name=first.tool_name,
            tool_args=first.tool_args,
            tool_call_id=first.tool_call_id,
            tool_calls=parsed,
        )
    return ProviderResponse(kind="message", content=getattr(message, "content", "") or "")
