"""Tests for Ollama provider options and tool-parse recovery."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.agent.session import SessionMessage, read_messages
from opentorus.config import default_config
from opentorus.errors import ProviderError, is_recoverable_tool_parse_error
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.providers.ollama_provider import build_ollama_chat_body, ollama_options
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


def test_is_recoverable_tool_parse_error() -> None:
    assert is_recoverable_tool_parse_error(
        ProviderError('Ollama returned HTTP 500: {"error":"error parsing tool call: raw=..."')
    )
    assert not is_recoverable_tool_parse_error(ProviderError("Could not reach Ollama"))


def test_ollama_options_default_num_predict_with_tools() -> None:
    config = default_config()
    opts = ollama_options(config, tools_enabled=True)
    assert opts["num_predict"] == -1


def test_ollama_options_respect_num_ctx_and_num_predict() -> None:
    config = default_config()
    config.model.num_ctx = 32768
    config.model.num_predict = 4096
    opts = ollama_options(config, tools_enabled=True)
    assert opts["num_ctx"] == 32768
    assert opts["num_predict"] == 4096


def test_build_ollama_chat_body_includes_tools() -> None:
    config = default_config()
    body = build_ollama_chat_body(
        config,
        [SessionMessage(role="user", content="hi")],
        [{"name": "status", "description": "d", "parameters": {"type": "object"}}],
    )
    assert body["options"]["num_predict"] == -1
    assert body["tools"][0]["function"]["name"] == "status"


class FlakyToolParseProvider(BaseProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None) -> ProviderResponse:
        self.calls += 1
        if self.calls == 1:
            raise ProviderError(
                "Ollama returned HTTP 500: "
                '{"error":"error parsing tool call: raw=\\"{\\"command\\""}'
            )
        if self.calls == 2:
            return ProviderResponse(kind="tool_call", tool_name="status", tool_args={})
        return ProviderResponse(kind="message", content="workspace_root=/tmp done")


def test_agent_loop_recovers_from_tool_parse_error(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    loop = AgentLoop(tmp_path, ot_dir, FlakyToolParseProvider(), registry, default_config())
    answer = loop.run("show status")
    assert "workspace_root" in answer
    msgs = read_messages(ot_dir)
    assert any(TOOL_PARSE_RECOVERY in m.content for m in msgs if m.role == "user")


from opentorus.agent.prompts import TOOL_PARSE_RECOVERY  # noqa: E402
