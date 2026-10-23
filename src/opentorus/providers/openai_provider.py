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
from types import SimpleNamespace

from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.errors import ProviderError
from opentorus.providers._convert import to_function_tools, to_openai_messages
from opentorus.providers.base import (
    BaseProvider,
    OnText,
    ProviderResponse,
    TokenUsage,
    ToolCallRequest,
    apportion_thinking,
)
from opentorus.providers.retry import (
    ContextLengthExceededError,
    FailureClass,
    RetryableFailure,
    call_with_retries,
    classify_status,
    is_context_length_message,
    parse_retry_after,
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
    # An OpenAI-compatible third-party endpoint differs in exactly two things: the
    # credential it reads and the endpoint it defaults to. Subclasses override these
    # two and inherit one request builder and one tool-call parser, so a wire-format
    # fix lands for every compatible provider at once.
    api_key_env = "OPENAI_API_KEY"
    default_base_url: str | None = None

    def __init__(self, config: Config) -> None:
        self.config = config
        # Opt-in SSE streaming (model.stream): text then reaches ``on_text`` as it arrives.
        self.supports_streaming = bool(getattr(config.model, "stream", False))
        # Fail here rather than at the first model call. The SDK is an optional
        # dependency, and when it was missing a run set up its whole workspace,
        # fetched papers, built a container and only then died inside step 1 —
        # the cost of finding out was an entire session's setup.
        _require_openai_sdk()

    def generate(
        self, messages: list[SessionMessage], tools: list[dict] | None = None
    ) -> ProviderResponse:
        return self._complete(messages, tools)

    def respond(
        self,
        messages: list[SessionMessage],
        tools: list[dict] | None = None,
        on_text: OnText | None = None,
        *,
        stream: bool = False,
        tool_choice: str | dict | None = None,
        on_thinking: OnText | None = None,
    ) -> ProviderResponse:
        response = self._complete(messages, tools, on_text=on_text, on_thinking=on_thinking)
        if on_text and not self.supports_streaming and response.kind == "message":
            if response.content:
                on_text(response.content)
        return response

    def _complete(
        self,
        messages: list[SessionMessage],
        tools: list[dict] | None,
        *,
        on_text: OnText | None = None,
        on_thinking: OnText | None = None,
    ) -> ProviderResponse:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ProviderError(
                f"{self.api_key_env} is not set. Put it in a .env file in your project "
                f"({self.api_key_env}=…) or export it to use the {self.name} provider."
            )
        OpenAI = _require_openai_sdk()

        kwargs = build_openai_request(self.config, messages, tools)
        client = OpenAI(
            **openai_client_kwargs(
                self.config, api_key=api_key, default_base_url=self.default_base_url
            )
        )
        # The failure-class retry below owns retries (long backoff when the endpoint
        # answered 408/425/429/5xx, short when it did not answer, never on other 4xx);
        # the SDK's own retries must not stack underneath it.
        with_options = getattr(client, "with_options", None)
        caller = with_options(max_retries=0) if callable(with_options) else client
        endpoint = _endpoint_key(self.name, self.config.model.base_url)
        known_bad = _REJECTED_FIELDS.setdefault(endpoint, set())
        for stale in known_bad & kwargs.keys():
            kwargs.pop(stale)
        _apply_effort_remap(endpoint, kwargs)
        streaming = bool(getattr(self.config.model, "stream", False))
        if streaming:
            kwargs["stream"] = True
            if "stream_options" not in known_bad:
                kwargs["stream_options"] = {"include_usage": True}
        adaptations = 0

        def attempt() -> ProviderResponse:
            nonlocal adaptations
            while True:
                try:
                    if streaming:
                        return self._read_stream(caller, kwargs, on_text, on_thinking)
                    return _parse_completion(
                        caller.chat.completions.create(**kwargs), self.config.model.max_tokens
                    )
                except (ProviderError, RetryableFailure):
                    raise
                except Exception as exc:  # noqa: BLE001 - translate, never leak the SDK's type
                    # An endpoint that rejects an optional field is answered by dropping
                    # (or re-mapping) that field — a bounded adaptation, not a retry.
                    if adaptations < 3 and _adapt_request(exc, kwargs, endpoint, self.name):
                        adaptations += 1
                        continue
                    raise _classified(exc, self.name) from exc

        return call_with_retries(
            attempt, max_retries=int(self.config.model.max_retries or 0), label=self.name
        )

    def _read_stream(
        self,
        caller: object,
        kwargs: dict,
        on_text: OnText | None,
        on_thinking: OnText | None,
    ) -> ProviderResponse:
        """Assemble a streamed completion; only a stream that never started is retried."""
        received = False
        content: list[str] = []
        thinking: list[str] = []
        calls: dict[int, dict] = {}
        finish: str | None = None
        usage: TokenUsage | None = None
        model: str | None = None
        stream = caller.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
        try:
            for chunk in stream:
                received = True
                model = getattr(chunk, "model", None) or model
                if getattr(chunk, "usage", None) is not None:
                    usage = _openai_usage(chunk)
                for choice in getattr(chunk, "choices", None) or []:
                    delta = getattr(choice, "delta", None)
                    text = getattr(delta, "content", None) if delta is not None else None
                    if text:
                        content.append(text)
                        if on_text is not None:
                            on_text(text)
                    # vLLM's reasoning parser streams the thinking as ``reasoning_content``
                    # (newer servers: ``reasoning``); it is shown, never the answer.
                    reasoning = getattr(delta, "reasoning_content", None) or getattr(
                        delta, "reasoning", None
                    )
                    if isinstance(reasoning, str) and reasoning:
                        thinking.append(reasoning)
                        if on_thinking is not None:
                            on_thinking(reasoning)
                    for call in (getattr(delta, "tool_calls", None) or []) if delta else []:
                        slot = calls.setdefault(
                            int(getattr(call, "index", 0) or 0),
                            {"id": None, "name": "", "arguments": ""},
                        )
                        if getattr(call, "id", None):
                            slot["id"] = call.id
                        function = getattr(call, "function", None)
                        if function is not None:
                            slot["name"] += getattr(function, "name", None) or ""
                            slot["arguments"] += getattr(function, "arguments", None) or ""
                    if getattr(choice, "finish_reason", None):
                        finish = str(choice.finish_reason)
        except Exception as exc:  # noqa: BLE001 - translate; maybe retry if nothing arrived
            if not received:
                raise
            raise ProviderError(
                f"{self.name} stream broke after the response had started "
                f"({type(exc).__name__}: {exc}). Not retried: part of the answer had already "
                "arrived, and a second attempt could differ from what was shown."
            ) from exc
        if finish is None:
            error = ProviderError(
                f"{self.name} stream ended without a finish_reason — the response is "
                "incomplete and was not accepted."
            )
            if not received:
                raise RetryableFailure(FailureClass.UNREACHABLE, error)
            raise error
        message = SimpleNamespace(
            content="".join(content),
            tool_calls=[
                SimpleNamespace(
                    id=slot["id"] or f"call_{index}",
                    function=SimpleNamespace(name=slot["name"], arguments=slot["arguments"]),
                )
                for index, slot in sorted(calls.items())
            ]
            or None,
        )
        truncated = _is_truncated(finish, usage, self.config.model.max_tokens)
        response = parse_openai_message(message, truncated=truncated)
        if usage is not None and thinking and not usage.thinking_tokens:
            usage.thinking_tokens = apportion_thinking(
                usage.completion_tokens, "".join(thinking), "".join(content)
            )
        response.usage = usage
        response.model = model
        response.truncated = truncated
        return response


def _is_truncated(finish: object, usage: TokenUsage | None, max_tokens: int | None) -> bool:
    """Did the reply stop at the output-token ceiling?

    ``finish_reason == "length"`` says so — but not always: vLLM (observed with a
    Qwen tool parser) reports ``"tool_calls"`` for a tool call cut off at
    ``max_tokens``, with the arguments either cut mid-string or silently shortened. So
    a reply whose completion tokens reached the configured cap counts as cut off too.
    """
    if finish == "length":
        return True
    if max_tokens and usage is not None and usage.completion_tokens >= int(max_tokens):
        return True
    return False


def _parse_completion(completion: object, max_tokens: int | None = None) -> ProviderResponse:
    choice = completion.choices[0]  # type: ignore[attr-defined]
    usage = _openai_usage(completion)
    truncated = _is_truncated(getattr(choice, "finish_reason", None), usage, max_tokens)
    response = parse_openai_message(choice.message, truncated=truncated)
    response.usage = usage
    # The model id the API reports (a routed alias may resolve to a dated snapshot).
    response.model = getattr(completion, "model", None) or None
    response.truncated = truncated
    return response


def _status_of(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _classified(exc: Exception, provider: str) -> RetryableFailure:
    """Wrap an SDK failure with its failure class (see ``providers.retry``)."""
    name = type(exc).__name__
    status = _status_of(exc)
    text = str(exc)
    if status is None:
        if name == "APITimeoutError" or isinstance(exc, TimeoutError):
            failure = FailureClass.TIMEOUT
        elif name == "APIConnectionError" or isinstance(exc, ConnectionError):
            failure = FailureClass.UNREACHABLE
        elif is_context_length_message(text):
            failure = FailureClass.CONTEXT_LENGTH
        else:
            failure = FailureClass.PERMANENT
    else:
        failure = classify_status(status, text)
    if failure is FailureClass.CONTEXT_LENGTH:
        return RetryableFailure(
            failure,
            ContextLengthExceededError(
                f"{provider}: the request does not fit the model's context window ({exc})"
            ),
        )
    headers = getattr(getattr(exc, "response", None), "headers", None)
    retry_after = None
    if headers is not None:
        try:
            retry_after = parse_retry_after(headers.get("retry-after"))
        except AttributeError:
            retry_after = None
    return RetryableFailure(failure, _provider_error(exc, provider), retry_after)


# Reasoning efforts in increasing order, across the vocabularies endpoints use.
_EFFORT_SCALE = ("minimal", "low", "medium", "high", "xhigh", "max")
# vLLM, for a model whose chat template defines its own levels:
#   400 "Unexpected reasoning effort high. Supported types are xhigh (default), medium,
#   and low."
_EFFORT_REJECTED = re.compile(
    r"Unexpected reasoning effort ['\"]?(?P<asked>\w+)['\"]?\.?\s*Supported "
    r"(?:types|values) (?:are|is)\s*(?P<supported>[^.\n]+)",
    re.IGNORECASE,
)
# endpoint -> {asked effort -> the nearest effort that endpoint accepts}
_EFFORT_REMAP: dict[str, dict[str, str]] = {}


def _nearest_effort(asked: str, supported: list[str]) -> str | None:
    known = [s for s in supported if s in _EFFORT_SCALE]
    if not known or asked not in _EFFORT_SCALE:
        return known[0] if known else None
    target = _EFFORT_SCALE.index(asked)
    # Ties go to the higher level: an asked-for effort is a request for more thinking.
    return min(known, key=lambda s: (abs(_EFFORT_SCALE.index(s) - target), -_EFFORT_SCALE.index(s)))


def _apply_effort_remap(endpoint: str, kwargs: dict) -> None:
    asked = kwargs.get("reasoning_effort")
    if isinstance(asked, str):
        mapped = _EFFORT_REMAP.get(endpoint, {}).get(asked)
        if mapped:
            kwargs["reasoning_effort"] = mapped


def _adapt_request(exc: Exception, kwargs: dict, endpoint: str, provider: str) -> bool:
    """Change the request so the endpoint can accept it; False when nothing applies."""
    text = str(exc)
    match = _EFFORT_REJECTED.search(text)
    asked = kwargs.get("reasoning_effort")
    if match is not None and isinstance(asked, str):
        supported = re.findall(r"[a-z]+", match.group("supported").lower())
        supported = [s for s in supported if s not in {"and", "or", "default"}]
        chosen = _nearest_effort(asked, supported)
        if chosen and chosen != asked:
            _logger.info(
                "%s does not take reasoning_effort=%r; using %r (supported: %s).",
                provider,
                asked,
                chosen,
                ", ".join(supported),
            )
            _EFFORT_REMAP.setdefault(endpoint, {})[asked] = chosen
            kwargs["reasoning_effort"] = chosen
            return True
    field = unsupported_request_field(exc)
    if field is None or field not in kwargs:
        return False
    _logger.info(
        "%s rejected the request field %r; dropping it for this endpoint.", provider, field
    )
    _REJECTED_FIELDS.setdefault(endpoint, set()).add(field)
    kwargs.pop(field)
    return True


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
_DROPPABLE_FIELDS = frozenset(
    {
        "seed",
        "top_p",
        "max_tokens",
        "temperature",
        "stream_options",
        "reasoning_effort",
        "chat_template_kwargs",
    }
)
# OpenAI's own wording for a parameter a model does not take:
#   400 "Unsupported parameter: 'reasoning_effort' is not supported with this model."
_UNSUPPORTED_PARAMETER = re.compile(
    r"Unsupported (?:parameter|value)s?:?\s*['\"](?P<field>[A-Za-z_][A-Za-z0-9_]*)['\"]"
)


# Remembered per endpoint for the life of the process. Without this the field is sent,
# rejected and retried on EVERY turn: a live Mistral run logged 14 rejections in its
# first 28 requests, doubling both the latency and the bill for the same answers.
_REJECTED_FIELDS: dict[str, set[str]] = {}


def _endpoint_key(provider: str, base_url: str | None) -> str:
    return f"{provider}@{base_url or 'default'}"


def unsupported_request_field(exc: Exception) -> str | None:
    """The optional request field this endpoint rejected as unknown, if it said so."""
    text = str(exc)
    match = _EXTRA_FORBIDDEN.search(text) or _UNSUPPORTED_PARAMETER.search(text)
    if match is None:
        return None
    field = match.group("field")
    if field not in _DROPPABLE_FIELDS:
        return None
    # chat_template_kwargs travels inside extra_body; dropping it drops that wrapper.
    return "extra_body" if field == "chat_template_kwargs" else field


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


def openai_client_kwargs(
    config: Config, *, api_key: str | None = None, default_base_url: str | None = None
) -> dict:
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
    elif default_base_url:
        # A compatible third-party endpoint (Mistral) that the user has not overridden.
        kwargs["base_url"] = default_base_url
    if api_key:
        kwargs["api_key"] = api_key
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
    kwargs.update(reasoning_request_fields(config))
    return kwargs


# OpenAI's ``reasoning_effort`` has no "off" and no "max": map onto its own scale.
_OPENAI_EFFORT = {"off": "minimal", "low": "low", "medium": "medium", "high": "high", "max": "high"}


def reasoning_request_fields(config: Config) -> dict:
    """Request fields that carry ``model.reasoning_effort`` to the endpoint.

    vLLM (and other servers that render a chat template) take the switch as
    ``chat_template_kwargs`` in the request body — Qwen3/Gemma templates read
    ``enable_thinking`` — which the SDK sends via ``extra_body``. OpenAI takes
    ``reasoning_effort``. ``model.reasoning_api`` picks one, both or neither; "auto"
    sends both to a custom ``base_url`` and only ``reasoning_effort`` to OpenAI. A field
    an endpoint rejects is dropped and remembered (see ``unsupported_request_field``).
    """
    effort = getattr(config.model, "reasoning_effort", None)
    if effort is None:
        return {}
    api = getattr(config.model, "reasoning_api", "auto")
    if api == "none":
        return {}
    if api == "auto":
        api = "both" if config.model.base_url else "reasoning_effort"
    fields: dict = {}
    if api in ("chat_template_kwargs", "both"):
        fields["extra_body"] = {"chat_template_kwargs": {"enable_thinking": effort != "off"}}
    if api in ("reasoning_effort", "both"):
        if api == "both" and effort == "off":
            # A chat-template server already has thinking switched off; "minimal" is an
            # OpenAI-only value a vLLM server would reject.
            return fields
        fields["reasoning_effort"] = _OPENAI_EFFORT[effort]
    return fields


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


def parse_openai_message(message: object, *, truncated: bool = False) -> ProviderResponse:
    """Parse a chat message; ``truncated`` = it stopped at the output-token limit.

    A cut-off reply routinely carries a tool call whose JSON arguments are cut off too.
    That is not a malformed call to correct but an incomplete reply: its calls are
    dropped unexecuted by the loop anyway, so unparseable arguments are kept as ``{}``
    here instead of raising the tool-parse error (which would hide the truncation).
    """
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        parsed: list[ToolCallRequest] = []
        for call in tool_calls:
            raw_args = call.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                if truncated:
                    args = {}
                    parsed.append(
                        ToolCallRequest(
                            tool_name=call.function.name, tool_args=args, tool_call_id=call.id
                        )
                    )
                    continue
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
            # A tool-call turn may carry text before its calls; keep it (it is what a
            # truncated reply preserves).
            content=strip_channel_markers(content_of(message)) if truncated else "",
            tool_name=first.tool_name,
            tool_args=first.tool_args,
            tool_call_id=first.tool_call_id,
            tool_calls=parsed,
            truncated=truncated,
        )
    return ProviderResponse(
        kind="message",
        content=strip_channel_markers(content_of(message)),
        truncated=truncated,
    )


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
