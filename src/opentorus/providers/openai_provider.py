"""OpenAI provider with tool calling.

Imports the SDK lazily and fails with an actionable message when the package or
API key is missing. Sends tools as OpenAI ``function`` tools and parses
``tool_calls`` back into a :class:`ProviderResponse`.
"""

from __future__ import annotations

import json
import logging
import os
import re

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

_logger = logging.getLogger("opentorus.providers")


def _require_openai_sdk() -> type:
    """Return the ``OpenAI`` client class, or raise the actionable install error."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderError(
            "The 'openai' package is not installed. Install it with: pip install openai"
        ) from exc
    return OpenAI


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, config: Config) -> None:
        self.config = config
        # Fail here rather than at the first model call. The SDK is an optional
        # dependency, and when it was missing a run set up its whole workspace,
        # fetched papers, built a container and only then died inside step 1 —
        # the cost of finding out was an entire session's setup.
        _require_openai_sdk()

    def generate(
        self, messages: list[SessionMessage], tools: list[dict] | None = None
    ) -> ProviderResponse:
        if not os.environ.get("OPENAI_API_KEY"):
            raise ProviderError(
                "OPENAI_API_KEY is not set. Put it in a .env file in your project "
                "(OPENAI_API_KEY=sk-…) or export it to use the OpenAI provider."
            )
        OpenAI = _require_openai_sdk()

        kwargs = build_openai_request(self.config, messages, tools)
        client = OpenAI(**openai_client_kwargs(self.config))
        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - translate, never leak the SDK's own type
            field = unsupported_request_field(exc)
            if field is None or field not in kwargs:
                raise _provider_error(exc, self.name) from exc
            _logger.info("%s rejected the request field %r; retrying without it.", self.name, field)
            kwargs.pop(field)
            try:
                completion = client.chat.completions.create(**kwargs)
            except Exception as retry_exc:  # noqa: BLE001 - same translation, second try
                raise _provider_error(retry_exc, self.name) from retry_exc
        choice = completion.choices[0]
        response = parse_openai_message(choice.message)
        response.usage = _openai_usage(completion)
        # The model id the API reports (a routed alias may resolve to a dated snapshot).
        response.model = getattr(completion, "model", None) or None
        # finish_reason "length" means the output hit the token ceiling (truncated).
        response.truncated = getattr(choice, "finish_reason", None) == "length"
        return response


# An OpenAI-compatible endpoint is not OpenAI. Mistral rejects `seed` outright:
#   422 {'type': 'extra_forbidden', 'loc': ['body', 'seed'], 'input': 5}
# and a run configured with a seed died on its first call. Rather than maintaining a
# per-provider table of what each endpoint accepts — which would be wrong the week any
# of them changes — read the field out of the rejection and retry once without it. The
# same shape is already used for tool_choice="required" in providers/tool_support.py.
_EXTRA_FORBIDDEN = re.compile(
    r"extra_forbidden.{0,120}?['\"]loc['\"]\s*:\s*\[[^\]]*?['\"](?P<field>[A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]",
    re.S,
)
# Optional sampling knobs only: never retry by dropping `messages`, `model` or `tools`,
# where a silent retry would change the question rather than the request shape.
_DROPPABLE_FIELDS = frozenset({"seed", "top_p", "max_tokens", "temperature", "stream_options"})


def unsupported_request_field(exc: Exception) -> str | None:
    """The optional request field this endpoint rejected as unknown, if it said so."""
    match = _EXTRA_FORBIDDEN.search(str(exc))
    if match is None:
        return None
    field = match.group("field")
    return field if field in _DROPPABLE_FIELDS else None


def _provider_error(exc: Exception, provider: str) -> ProviderError:
    """Turn an SDK exception into a ProviderError that says what to do about it.

    A rate limit reached the user as a 40-line rich traceback ending in
    ``RateLimitError: Error code: 429``, after the run had already spent real money —
    the SDK's retries were exhausted and nothing above translated the failure. The type
    is matched by name so this needs no import of the SDK's exception hierarchy.
    """
    name = type(exc).__name__
    if name == "RateLimitError" or getattr(exc, "status_code", None) == 429:
        return ProviderError(
            f"{provider} rate-limited the request (HTTP 429) and the configured retries "
            "were exhausted. Raise model.max_retries, lower the number of parallel "
            f"runs, or wait for the quota window to reset. ({exc})"
        )
    if name in {"APITimeoutError", "APIConnectionError"}:
        return ProviderError(
            f"Could not reach the {provider} endpoint ({name}). Check the network and "
            f"model.base_url, or raise model.timeout_seconds. ({exc})"
        )
    if name == "AuthenticationError" or getattr(exc, "status_code", None) == 401:
        return ProviderError(
            f"{provider} rejected the credentials (HTTP 401). Check the API key in your "
            f".env or environment. ({exc})"
        )
    return ProviderError(f"{provider} request failed ({name}): {exc}")


def openai_client_kwargs(config: Config) -> dict:
    """Constructor arguments for the ``openai`` client.

    ``model.base_url`` selects the endpoint — an OpenAI-compatible server (vLLM,
    llama.cpp, LM Studio, a proxy) as much as OpenAI itself; unset keeps the SDK's
    default (``OPENAI_BASE_URL`` or api.openai.com). It used to be ignored here, so a
    ``base_url`` pointing at a vLLM server silently talked to OpenAI instead.
    ``model.timeout_seconds`` bounds every request the same way it does for Ollama.
    """
    kwargs: dict = {}
    if config.model.base_url:
        kwargs["base_url"] = config.model.base_url
    if config.model.timeout_seconds:
        kwargs["timeout"] = float(config.model.timeout_seconds)
    # The SDK retries 429/5xx with exponential backoff and honours Retry-After; its own
    # default of 2 is short for an agent run that talks to a metered endpoint for hours.
    retries = getattr(config.model, "max_retries", None)
    if retries is not None:
        kwargs["max_retries"] = max(0, int(retries))
    return kwargs


def build_openai_request(
    config: Config, messages: list[SessionMessage], tools: list[dict] | None
) -> dict:
    """The ``chat.completions.create`` arguments: model, sampling shape, messages, tools.

    ``max_tokens``, ``top_p`` and ``seed`` are forwarded only when set, so an unset
    field keeps the server's own default (the same contract as the Ollama options).
    """
    kwargs: dict = {
        "model": config.model.name,
        "temperature": config.model.temperature,
        "messages": to_openai_messages(messages),
    }
    if config.model.max_tokens is not None:
        kwargs["max_tokens"] = config.model.max_tokens
    if config.model.top_p is not None:
        kwargs["top_p"] = config.model.top_p
    if config.model.seed is not None:
        kwargs["seed"] = config.model.seed
    if tools:
        kwargs["tools"] = to_function_tools(tools)
    return kwargs


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
    return ProviderResponse(kind="message", content=strip_channel_markers(content_of(message)))


# Gemma 4 emits its thinking as a "channel": ``<|channel>thought ... <channel|>`` before the
# answer. A vLLM server started without ``--reasoning-parser gemma4`` passes the markers
# through as ordinary content (observed: ``'<|channel>thought\n<channel|>The workspace …'``);
# an OpenAI-compatible server without a reasoning parser is the common case, so the
# provider strips them here. The thinking text is dropped, not shown as the answer.
_CHANNEL_BLOCK = re.compile(r"<\|channel>thought\s*(.*?)<channel\|>", re.DOTALL)
_STRAY_MARKERS = re.compile(r"<\|channel>thought\s*|<channel\|>")


def content_of(message: object) -> str:
    return str(getattr(message, "content", "") or "")


def strip_channel_markers(text: str) -> str:
    """Remove Gemma-4 thinking-channel blocks and stray markers from a reply."""
    if "<|channel>" not in text and "<channel|>" not in text:
        return text
    cleaned = _CHANNEL_BLOCK.sub("", text)
    cleaned = _STRAY_MARKERS.sub("", cleaned)
    return cleaned.strip()
