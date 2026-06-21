"""Tests for Ollama provider options and tool-parse recovery."""

from __future__ import annotations

from pathlib import Path

import pytest

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
from opentorus.providers.ollama_provider import (  # noqa: E402
    clean_harmony_tool_name,
    parse_ollama_message,
)


def test_clean_harmony_tool_name_passes_valid_names() -> None:
    assert clean_harmony_tool_name("read_file") == "read_file"
    assert clean_harmony_tool_name("proof_write") == "proof_write"
    assert clean_harmony_tool_name("  status  ") == "status"


def test_clean_harmony_tool_name_drops_bare_channel_marker() -> None:
    # The exact leak that broke the OpenAI request: a commentary preamble with no
    # to=functions.X recipient is not a tool call.
    assert clean_harmony_tool_name("assistant<|channel|>commentary") is None
    assert clean_harmony_tool_name("<|channel|>analysis") is None
    assert clean_harmony_tool_name("commentary") is None
    assert clean_harmony_tool_name("analysis") is None
    assert clean_harmony_tool_name("final") is None
    assert clean_harmony_tool_name("assistant") is None


def test_clean_harmony_tool_name_recovers_real_function_name() -> None:
    # When the recipient leaks too, recover the actual tool name from functions.NAME.
    assert clean_harmony_tool_name("commentary to=functions.read_file") == "read_file"
    assert (
        clean_harmony_tool_name(
            "assistant<|channel|>commentary to=functions.proof_write <|constrain|>json"
        )
        == "proof_write"
    )
    assert clean_harmony_tool_name("to=functions.status") == "status"


def test_clean_harmony_tool_name_handles_builtin_namespace_recipient() -> None:
    # Builtin recipients like to=browser.search reduce to the last segment.
    assert clean_harmony_tool_name("commentary to=browser.search") == "search"


def test_clean_harmony_tool_name_rejects_empty_and_non_str() -> None:
    assert clean_harmony_tool_name("") is None
    assert clean_harmony_tool_name("   ") is None
    assert clean_harmony_tool_name(None) is None
    assert clean_harmony_tool_name(123) is None


def test_clean_harmony_tool_name_passes_unusual_non_framing_names_through() -> None:
    # A name that does not look like harmony framing is returned unchanged — the registry
    # / loop validates it. This is the safe default: never DROP a possibly-legitimate name.
    assert clean_harmony_tool_name("just some prose with spaces") == "just some prose with spaces"


def test_clean_harmony_tool_name_preserves_mcp_namespaced_names() -> None:
    # MCP tools register as mcp__<server>__<tool> (tools/mcp.py). They must pass through
    # unchanged, including dotted remote/server segments the OpenAI gate would reject —
    # dropping them would silently disable the tool with no error (review finding, high).
    assert clean_harmony_tool_name("mcp__github__create_issue") == "mcp__github__create_issue"
    assert clean_harmony_tool_name("mcp__weather__get.forecast") == "mcp__weather__get.forecast"
    assert clean_harmony_tool_name("mcp__db__query.select") == "mcp__db__query.select"
    # A name whose segment embeds 'functions.' or 'to=X' (no real recipient) must NOT be
    # rewritten to a wrong tool — recovery is anchored on a 'to=' recipient.
    assert clean_harmony_tool_name("mcp__x__functions.helper") == "mcp__x__functions.helper"
    # Recovery from a real header keeps the full namespaced name.
    assert (
        clean_harmony_tool_name("commentary to=functions.mcp__github__create_issue")
        == "mcp__github__create_issue"
    )


def test_clean_harmony_tool_name_recovery_is_anchored_on_recipient() -> None:
    # A function merely MENTIONED in a commentary preamble must not be dispatched; only
    # the actual to=functions.NAME recipient is recovered (review finding, false positive).
    assert (
        clean_harmony_tool_name(
            "assistant<|channel|>commentary I will not use functions.delete_file; "
            "instead to=functions.read_file <|constrain|>json"
        )
        == "read_file"
    )
    # First recipient wins when several appear (pins the documented segmentation contract).
    assert clean_harmony_tool_name("to=functions.first then to=functions.second") == "first"


def test_clean_harmony_tool_name_drops_channel_role_recipients() -> None:
    # A recipient that resolves to a harmony channel/role/namespace keyword is framing,
    # not a tool — it must be dropped, not leaked (review finding, contract violation).
    assert clean_harmony_tool_name("assistant<|channel|>commentary to=commentary") is None
    assert clean_harmony_tool_name("to=functions") is None
    assert clean_harmony_tool_name("to=analysis") is None
    assert clean_harmony_tool_name("to=assistant") is None


def test_clean_harmony_tool_name_is_case_insensitive_for_markers() -> None:
    # Case-variant channel/role markers are still framing, not tool names.
    assert clean_harmony_tool_name("Commentary") is None
    assert clean_harmony_tool_name("ASSISTANT") is None
    assert clean_harmony_tool_name("to=Commentary") is None


def test_parse_ollama_message_drops_harmony_only_tool_call() -> None:
    # A single harmony-framed "tool call" with no recipient becomes a message, not a
    # bogus tool call (which would corrupt the session and break OpenAI on resume).
    msg = {
        "role": "assistant",
        "content": "Let me think about this.",
        "tool_calls": [{"function": {"name": "assistant<|channel|>commentary", "arguments": {}}}],
    }
    result = parse_ollama_message(msg)
    assert result.kind == "message"
    assert result.content == "Let me think about this."


def test_parse_ollama_message_keeps_valid_drops_garbage_in_same_turn() -> None:
    msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "assistant<|channel|>commentary", "arguments": {}}},
            {"function": {"name": "read_file", "arguments": {"path": "a.md"}}},
        ],
    }
    result = parse_ollama_message(msg)
    assert result.kind == "tool_call"
    assert [tc.tool_name for tc in result.tool_calls] == ["read_file"]
    assert result.tool_args == {"path": "a.md"}


def test_parse_ollama_message_recovers_framed_call_with_args() -> None:
    msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "function": {
                    "name": "commentary to=functions.status",
                    "arguments": {},
                }
            }
        ],
    }
    result = parse_ollama_message(msg)
    assert result.kind == "tool_call"
    assert result.tool_name == "status"


def test_parse_ollama_message_handles_missing_function_key() -> None:
    # A tool_calls entry with no 'function' key must not crash; it degrades to a message.
    result = parse_ollama_message(
        {"role": "assistant", "content": "x", "tool_calls": [{"id": "c1"}]}
    )
    assert result.kind == "message"
    assert result.content == "x"


def test_parse_ollama_message_keeps_all_valid_calls_in_order() -> None:
    result = parse_ollama_message(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "a.md"}}},
                {"function": {"name": "status", "arguments": {}}},
            ],
        }
    )
    assert result.kind == "tool_call"
    assert [tc.tool_name for tc in result.tool_calls] == ["read_file", "status"]


def test_parse_ollama_message_harmony_only_without_content_key() -> None:
    result = parse_ollama_message(
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "assistant<|channel|>commentary"}}],
        }
    )
    assert result.kind == "message"
    assert result.content == ""


def test_ollama_stream_valid_call_survives_later_garbage_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A valid tool call in one delta must not be lost when a later delta carries only
    # harmony-framing garbage (the streaming accumulator must not overwrite earlier
    # calls; review finding, medium).
    from opentorus.providers.ollama_provider import OllamaProvider

    lines = [
        b'{"message":{"role":"assistant","content":"",'
        b'"tool_calls":[{"function":{"name":"read_file","arguments":{"path":"x.md"}}}]},'
        b'"done":false}\n',
        b'{"message":{"role":"assistant","content":"",'
        b'"tool_calls":[{"function":{"name":"assistant<|channel|>commentary",'
        b'"arguments":{}}}]},"done":false}\n',
        b'{"message":{"role":"assistant","content":""},"done":true}\n',
    ]

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def __iter__(self):
            return iter(lines)

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse())
    config = default_config()
    config.model.provider = "ollama"
    provider = OllamaProvider(config)
    response = provider.respond(
        [SessionMessage(role="user", content="read it")],
        tools=[{"name": "read_file", "description": "", "parameters": {}}],
        stream=True,
    )
    assert response.kind == "tool_call"
    assert response.tool_name == "read_file"
    assert response.tool_args == {"path": "x.md"}
