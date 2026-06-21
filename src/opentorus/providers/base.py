"""Provider interface and response type.

A :class:`ProviderResponse` is either a final message to the user or a request to
call one or more tools. The agent loop alternates between asking the provider and
executing the requested tool calls (in order) until a message is returned.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.agent.session import SessionMessage

# Called with each incremental text chunk of a streamed message response.
OnText = Callable[[str], None]


def provider_label(provider: BaseProvider) -> str:
    """Human-readable model name for progress messages (not just ``ollama`` / ``openai``)."""
    config = getattr(provider, "config", None)
    if config is not None:
        model_name = getattr(getattr(config, "model", None), "name", None)
        if model_name and model_name not in ("mock-default",):
            return str(model_name)
    return getattr(provider, "name", "model")


class ToolCallRequest(BaseModel):
    """One tool call requested by the model within a single turn."""

    tool_name: str
    tool_args: dict = Field(default_factory=dict)
    tool_call_id: str | None = None


def apportion_thinking(completion_tokens: int, thinking_text: str, other_text: str) -> int:
    """Split an exact completion-token total into its thinking share.

    Ollama and Anthropic report the *exact* total output tokens (which already
    include thinking) but no separate thinking count. Estimating the thinking
    text independently (e.g. chars/token) is inaccurate and inconsistent with the
    exact total — reasoning text runs closer to ~3 chars/token, so a 4-chars
    estimate undercounts by tens of percent. Instead, apportion the exact total by
    character share, so the thinking subcount is on the same scale as ``out`` and
    never exceeds it. Returns 0 when there is no thinking text.
    """
    thinking_chars = len(thinking_text)
    if thinking_chars == 0 or completion_tokens <= 0:
        return 0
    total_chars = thinking_chars + len(other_text)
    if total_chars == 0:
        return 0
    return min(completion_tokens, round(completion_tokens * thinking_chars / total_chars))


class TokenUsage(BaseModel):
    """Exact token counts a provider reported for one turn.

    Populated from the provider API's own usage figures (OpenAI ``usage``,
    Anthropic ``usage``, Ollama ``prompt_eval_count``/``eval_count``). When a
    provider does not report usage (e.g. the offline mock), this stays ``None``
    and the caller falls back to a local character-count estimate.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Reasoning/"thinking" tokens generated this turn. Providers bill thinking as
    # output, so this is a subset of ``completion_tokens`` (not added on top),
    # surfaced separately for visibility. Exact when the provider reports it
    # (OpenAI ``reasoning_tokens``); otherwise estimated from the thinking text.
    thinking_tokens: int = 0


class ProviderResponse(BaseModel):
    kind: Literal["message", "tool_call"]
    content: str = ""
    # Scalar fields mirror the *first* tool call for backward compatibility.
    tool_name: str | None = None
    tool_args: dict = Field(default_factory=dict)
    tool_call_id: str | None = None
    # All tool calls the model requested this turn (may be more than one). When a
    # provider populates this, the loop executes every call in order; when empty,
    # the scalar fields above describe the single call.
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    # Exact token usage from the provider, when available (else None → estimate).
    usage: TokenUsage | None = None
    # True when the provider stopped at the token ceiling (stop/finish reason
    # "max_tokens"/"length"): the output is cut off, not a complete answer.
    truncated: bool = False

    def iter_tool_calls(self) -> list[ToolCallRequest]:
        """Normalized list of tool calls to execute (handles the scalar fallback)."""
        if self.tool_calls:
            return self.tool_calls
        if self.kind == "tool_call":
            return [
                ToolCallRequest(
                    tool_name=self.tool_name or "",
                    tool_args=self.tool_args,
                    tool_call_id=self.tool_call_id,
                )
            ]
        return []


class BaseProvider(ABC):
    """Common interface for all model providers.

    ``tools`` is a list of provider-neutral tool specs (``{name, description,
    parameters}``); each provider translates them into its own API format. A
    ``ProviderResponse`` is either a final message or a single tool call.
    """

    name: str = "base"
    # Whether ``respond`` emits text incrementally (vs. a single final chunk).
    supports_streaming: bool = False

    @abstractmethod
    def generate(
        self,
        messages: list[SessionMessage],
        tools: list[dict] | None = None,
    ) -> ProviderResponse:  # pragma: no cover - interface
        raise NotImplementedError

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
        """Return a response, streaming a message's text via ``on_text`` if given.

        The default implementation is non-streaming: it calls :meth:`generate` and
        emits the whole message as a single chunk. Streaming providers override
        this to emit incremental chunks while still returning the assembled
        ``ProviderResponse`` (so persistence is unchanged).
        """
        response = self.generate(messages, tools)
        if on_text and response.kind == "message" and response.content:
            on_text(response.content)
        return response
