"""Scripted provider doubles for driving the agent loops deterministically.

The suite grew a dozen ad-hoc ``_ScriptedProvider`` classes, each subtly different
(some pop, some cycle, some ignore ``on_text``). This one is the shared shape the
campaign-engine tests build on: responses are consumed in order, the last one repeats
once the script is exhausted (so a loop that keeps asking gets a stable answer instead
of an ``IndexError``), and every request is recorded for assertions.
"""

from __future__ import annotations

from collections.abc import Callable

from opentorus.agent.session import SessionMessage
from opentorus.providers.base import BaseProvider, ProviderResponse


class ScriptedProvider(BaseProvider):
    """Return queued responses in order; the last one repeats when exhausted.

    ``name`` and ``model_name`` are constructor arguments so a test can stand in for
    a cloud provider (``name="openai"``) or pin the model the usage ledger should see.
    ``calls`` records ``(messages, tools)`` per request, in order.
    """

    supports_streaming = False

    def __init__(
        self,
        responses: list[ProviderResponse],
        *,
        name: str = "scripted",
        model_name: str | None = None,
    ) -> None:
        if not responses:
            raise ValueError("ScriptedProvider needs at least one response")
        self.name = name
        self._model_name = model_name
        self._responses = list(responses)
        self.calls: list[tuple[list[SessionMessage], list[dict] | None]] = []

    @property
    def model_name(self) -> str | None:
        """The model this double pretends to be (``None`` = unspecified)."""
        return self._model_name

    @property
    def remaining(self) -> int:
        """Responses not yet handed out (the last one is never removed)."""
        return len(self._responses)

    def generate(
        self, messages: list[SessionMessage], tools: list[dict] | None = None
    ) -> ProviderResponse:
        self.calls.append((list(messages), tools))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]

    def respond(
        self,
        messages: list[SessionMessage],
        tools: list[dict] | None = None,
        on_text: Callable[[str], None] | None = None,
        *,
        stream: bool = False,
        tool_choice: str | dict | None = None,
        on_thinking: Callable[[str], None] | None = None,
    ) -> ProviderResponse:
        response = self.generate(messages, tools)
        if on_text and response.kind == "message" and response.content:
            on_text(response.content)
        return response


def tool_call(
    name: str, args: dict | None = None, *, call_id: str | None = None
) -> ProviderResponse:
    """Shorthand for a single-tool-call response."""
    return ProviderResponse(
        kind="tool_call", tool_name=name, tool_args=dict(args or {}), tool_call_id=call_id
    )


def message(content: str) -> ProviderResponse:
    """Shorthand for a chat-only response."""
    return ProviderResponse(kind="message", content=content)
