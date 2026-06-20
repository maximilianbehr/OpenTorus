"""Ollama provider for local models, with tool calling.

Talks to a local Ollama server over HTTP using only the standard library, so no
extra dependency is required. Supports the ``/api/chat`` ``tools`` field and
parses ``message.tool_calls`` back into a :class:`ProviderResponse`. Fails
clearly if the server is unreachable.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.errors import ProviderError
from opentorus.providers._convert import to_function_tools, to_ollama_messages
from opentorus.providers.base import (
    BaseProvider,
    OnText,
    ProviderResponse,
    TokenUsage,
    ToolCallRequest,
    apportion_thinking,
)

DEFAULT_HOST = "http://localhost:11434"


def ollama_options(config: Config, *, tools_enabled: bool) -> dict:
    """Build Ollama ``options`` for ``/api/chat``."""
    opts: dict = {"temperature": config.model.temperature}
    if config.model.num_ctx is not None:
        opts["num_ctx"] = config.model.num_ctx
    num_predict = config.model.num_predict
    if num_predict is None and tools_enabled:
        num_predict = -1
    if num_predict is not None:
        opts["num_predict"] = num_predict
    return opts


def build_ollama_chat_body(
    config: Config,
    messages: list[SessionMessage],
    tools: list[dict] | None,
    *,
    stream: bool = False,
    tool_choice: str | dict | None = None,
) -> dict:
    body: dict = {
        "model": config.model.name,
        "stream": stream,
        "options": ollama_options(config, tools_enabled=bool(tools)),
        "messages": to_ollama_messages(messages),
    }
    if tools:
        body["tools"] = to_function_tools(tools)
    if tool_choice is not None and tools:
        body["tool_choice"] = tool_choice
    return body


class OllamaProvider(BaseProvider):
    name = "ollama"
    supports_streaming = True

    def __init__(self, config: Config) -> None:
        self.config = config
        self.host = (config.model.base_url or DEFAULT_HOST).rstrip("/")

    def generate(
        self, messages: list[SessionMessage], tools: list[dict] | None = None
    ) -> ProviderResponse:
        return self._chat(messages, tools, stream=False, on_text=None)

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
        return self._chat(
            messages,
            tools,
            stream=stream,
            on_text=on_text,
            tool_choice=tool_choice,
            on_thinking=on_thinking,
        )

    def _chat(
        self,
        messages: list[SessionMessage],
        tools: list[dict] | None,
        *,
        stream: bool,
        on_text: OnText | None,
        tool_choice: str | dict | None = None,
        on_thinking: OnText | None = None,
    ) -> ProviderResponse:
        body = build_ollama_chat_body(
            self.config, messages, tools, stream=stream, tool_choice=tool_choice
        )

        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            timeout = self.config.model.timeout_seconds
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if stream:
                    return self._read_stream(response, on_text, on_thinking)
                data = json.loads(response.read().decode("utf-8"))
                msg = data.get("message", {})
                result = parse_ollama_message(msg)
                usage = _ollama_usage(data)
                if usage is not None:
                    thinking = msg.get("thinking") or msg.get("reasoning") or ""
                    other = (msg.get("content") or "") + json.dumps(msg.get("tool_calls") or [])
                    usage.thinking_tokens = apportion_thinking(
                        usage.completion_tokens, thinking, other
                    )
                result.usage = usage
                return result
        except TimeoutError as exc:
            raise ProviderError(
                f"Ollama timed out after {self.config.model.timeout_seconds}s waiting for "
                f"model '{self.config.model.name}'. The context may be too large, or the "
                f"model is slow — try a smaller model, reduce tools.web.max_chars, or raise "
                f"model.timeout_seconds in config."
            ) from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            hint = ""
            if "error parsing tool call" in detail.lower() or "parse json" in detail.lower():
                hint = (
                    " The model emitted invalid or truncated tool-call JSON — use write_file "
                    "for scripts and run_shell with a short one-liner; raise model.num_ctx "
                    "or upgrade Ollama if this persists."
                )
            raise ProviderError(
                f"Ollama returned HTTP {exc.code} for model "
                f"'{self.config.model.name}': {detail or exc.reason}.{hint}"
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderError(
                    f"Ollama timed out after {self.config.model.timeout_seconds}s waiting for "
                    f"model '{self.config.model.name}'. The context may be too large, or the "
                    f"model is slow — try a smaller model, reduce tools.web.max_chars, or raise "
                    f"model.timeout_seconds in config."
                ) from exc
            raise ProviderError(
                f"Could not reach Ollama at {self.host}. Is `ollama serve` running? ({exc})"
            ) from exc

    def _read_stream(
        self,
        response: object,
        on_text: OnText | None,
        on_thinking: OnText | None = None,
    ) -> ProviderResponse:
        accumulated = ""
        accumulated_thinking = ""
        role = "assistant"
        tool_calls: list | None = None
        usage: TokenUsage | None = None
        for raw_line in response:  # type: ignore[attr-defined]
            if not raw_line:
                continue
            chunk = json.loads(raw_line.decode("utf-8"))
            # The final ``done`` chunk carries the exact token counts.
            chunk_usage = _ollama_usage(chunk)
            if chunk_usage is not None:
                usage = chunk_usage
            message = chunk.get("message") or {}
            if message.get("role"):
                role = message["role"]
            # Reasoning models (qwen3, deepseek-r1, …) stream their chain of thought
            # in a separate ``thinking`` field before any ``content`` — surface it so
            # the user sees live progress instead of a silent multi-second spinner.
            thinking = message.get("thinking") or message.get("reasoning") or ""
            if thinking:
                accumulated_thinking += thinking
                if on_thinking is not None:
                    on_thinking(thinking)
            content = message.get("content") or ""
            if content:
                accumulated += content
                if on_text is not None:
                    on_text(content)
            # Tool calls arrive in their own delta; the final ``done`` chunk has an
            # empty message, so capture them separately and never let ``done``
            # clobber them (otherwise streamed tool calls are silently dropped).
            if message.get("tool_calls"):
                tool_calls = message["tool_calls"]
        last_message: dict = {"role": role, "content": accumulated}
        if tool_calls:
            last_message["tool_calls"] = tool_calls
        result = parse_ollama_message(last_message)
        if usage is not None and accumulated_thinking:
            other = accumulated + json.dumps(tool_calls or [])
            usage.thinking_tokens = apportion_thinking(
                usage.completion_tokens, accumulated_thinking, other
            )
        result.usage = usage
        return result


def _ollama_usage(data: dict) -> TokenUsage | None:
    """Exact token counts from an Ollama response/chunk, or None if absent."""
    prompt = data.get("prompt_eval_count")
    completion = data.get("eval_count")
    if prompt is None and completion is None:
        return None
    return TokenUsage(prompt_tokens=int(prompt or 0), completion_tokens=int(completion or 0))


def parse_ollama_message(message: dict) -> ProviderResponse:
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        parsed: list[ToolCallRequest] = []
        for tc in tool_calls:
            function = tc.get("function", {})
            name = function.get("name", "")
            args = function.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError as exc:
                    # Recoverable tool-parse error → the loop retries with a hint
                    # rather than calling the tool with empty arguments.
                    raise ProviderError(
                        f"Failed to parse JSON tool-call arguments for '{name}': {exc}."
                    ) from exc
            parsed.append(
                ToolCallRequest(
                    tool_name=name,
                    tool_args=args or {},
                    tool_call_id=tc.get("id") or uuid.uuid4().hex,
                )
            )
        first = parsed[0]
        return ProviderResponse(
            kind="tool_call",
            tool_name=first.tool_name,
            tool_args=first.tool_args,
            tool_call_id=first.tool_call_id,
            tool_calls=parsed,
        )
    return ProviderResponse(kind="message", content=message.get("content", ""))
