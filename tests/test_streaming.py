"""Tests for streaming responses (Milestone 30)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


def test_mock_streams_chunks_that_reassemble() -> None:
    provider = MockProvider()
    assert provider.supports_streaming is True
    chunks: list[str] = []
    response = provider.respond([], tools=None, on_text=chunks.append)
    # generate() with no messages -> "No input received."
    assert response.kind == "message"
    assert "".join(chunks) == response.content
    assert len(chunks) > 1  # actually streamed in pieces


def test_default_respond_is_single_chunk() -> None:
    class OneShot(BaseProvider):
        name = "oneshot"

        def generate(self, messages, tools=None) -> ProviderResponse:
            return ProviderResponse(kind="message", content="hello world here")

    chunks: list[str] = []
    OneShot().respond([], on_text=chunks.append)
    assert chunks == ["hello world here"]


def test_loop_streams_final_message(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    chunks: list[str] = []
    loop = AgentLoop(
        tmp_path, ot, MockProvider(), registry, default_config(), on_text=chunks.append
    )
    answer = loop.run("just chat, no tools")
    assert "".join(chunks) == answer


def test_tool_call_turns_do_not_stream_text(tmp_path: Path) -> None:
    # When the provider asks for a tool, the (empty) tool-call turn streams nothing;
    # only the final assembled message is streamed.
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    chunks: list[str] = []
    loop = AgentLoop(
        tmp_path, ot, MockProvider(), registry, default_config(), on_text=chunks.append
    )
    answer = loop.run("show me the status")
    assert "".join(chunks) == answer
    assert answer  # a final message was produced
