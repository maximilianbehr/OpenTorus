"""A deterministic provider for tests and offline use.

It never calls an external service. It inspects the latest message and either
requests a relevant read-only tool or returns a direct, honest placeholder
answer. After a tool runs, it summarizes the result and explicitly notes that no
validation was performed.
"""

from __future__ import annotations

import re

from opentorus.agent.session import SessionMessage
from opentorus.providers.base import BaseProvider, OnText, ProviderResponse


class MockProvider(BaseProvider):
    name = "mock"
    supports_streaming = True

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
        response = self.generate(messages, tools)
        if on_text and response.kind == "message" and response.content:
            # Emit word-by-word chunks that concatenate back to the full content.
            for chunk in re.findall(r"\S+\s*", response.content):
                on_text(chunk)
        return response

    def generate(
        self,
        messages: list[SessionMessage],
        tools: list[dict] | None = None,
    ) -> ProviderResponse:
        if not messages:
            return ProviderResponse(kind="message", content="No input received.")

        last = messages[-1]
        if last.role == "tool":
            return ProviderResponse(
                kind="message",
                content=(
                    "Here is what I found:\n\n"
                    f"{last.content}\n\n"
                    "This is observed output, not a validated conclusion. "
                    "Validation not run."
                ),
            )

        task = _last_user_text(messages).lower()
        available = {spec["name"] for spec in (tools or [])}

        if "status" in task and "status" in available:
            return ProviderResponse(kind="tool_call", tool_name="status")
        if "diff" in task and "git_diff" in available:
            return ProviderResponse(kind="tool_call", tool_name="git_diff")
        if "memory" in task and "memory_list" in available:
            return ProviderResponse(
                kind="tool_call", tool_name="memory_list", tool_args={"kind": "facts"}
            )

        return ProviderResponse(
            kind="message",
            content=(
                "I'm running with the deterministic mock provider (no LLM configured). "
                "I can inspect 'status', 'diff', or 'memory'. Configure a real provider "
                "with `opentorus config set model.provider <name>`."
            ),
        )


def _last_user_text(messages: list[SessionMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""
