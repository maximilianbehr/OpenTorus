"""Tests for MCP / external tool plugins (Milestone 32)."""

from __future__ import annotations

import sys
from pathlib import Path

from opentorus.config import Config, McpServerConfig, default_config
from opentorus.permissions.policy import evaluate_external_tool
from opentorus.tools.base import ToolCall
from opentorus.tools.builtin import build_default_registry
from opentorus.tools.mcp import McpClient, discover_mcp_tools, register_mcp_tools

_STUB = str(Path(__file__).parent / "mcp_stub_server.py")


def _server(enabled: bool = True) -> McpServerConfig:
    return McpServerConfig(name="stub", command=sys.executable, args=[_STUB], enabled=enabled)


def _config_with_stub(enabled: bool = True) -> Config:
    config = default_config()
    config.tools.mcp = [_server(enabled)]
    return config


def test_client_lists_and_calls_tools() -> None:
    with McpClient(sys.executable, [_STUB]) as client:
        tools = client.list_tools()
        assert [t["name"] for t in tools] == ["echo"]
        assert client.call_tool("echo", {"text": "hi"}) == "echoed: hi"


def test_discover_wraps_remote_tools() -> None:
    tools = discover_mcp_tools(_config_with_stub())
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "mcp__stub__echo"
    assert tool.permission == "external"
    result = tool.run(ToolCall(name=tool.name, args={"text": "world"}))
    assert result.ok
    assert result.content == "echoed: world"


def test_disabled_server_hides_tools() -> None:
    assert discover_mcp_tools(_config_with_stub(enabled=False)) == []


def test_registry_registers_mcp_tools() -> None:
    config = _config_with_stub()
    registry = build_default_registry(Path("."), Path("."), config)
    assert registry.get("mcp__stub__echo") is not None


def test_registry_without_config_has_no_mcp() -> None:
    registry = build_default_registry(Path("."), Path("."))
    assert all(not name.startswith("mcp__") for name in registry.names())


def test_register_returns_names() -> None:
    config = _config_with_stub()
    registry = build_default_registry(Path("."), Path("."))
    names = register_mcp_tools(registry, config)
    assert names == ["mcp__stub__echo"]


def test_external_policy_blocks_in_safe_and_review() -> None:
    safe = evaluate_external_tool("mcp__stub__echo", "safe")
    assert not safe.allowed
    review = evaluate_external_tool("mcp__stub__echo", "trusted", review=True)
    assert not review.allowed


def test_external_policy_confirms_in_ask() -> None:
    decision = evaluate_external_tool("mcp__stub__echo", "ask")
    assert decision.allowed
    assert decision.requires_confirmation


def test_external_policy_autonomous_no_confirm() -> None:
    decision = evaluate_external_tool("mcp__stub__echo", "trusted", style="autonomous")
    assert decision.allowed
    assert not decision.requires_confirmation


def test_mcp_result_is_capped() -> None:
    # A remote server is untrusted; an oversized result must be truncated before
    # it reaches the model context.
    from opentorus.tools.mcp import _MCP_RESULT_MAX_CHARS, _render_tool_result

    huge = {"content": [{"type": "text", "text": "x" * (_MCP_RESULT_MAX_CHARS + 5000)}]}
    rendered = _render_tool_result(huge)
    assert len(rendered) < _MCP_RESULT_MAX_CHARS + 200
    assert "truncated" in rendered


def test_mcp_small_result_is_unchanged() -> None:
    from opentorus.tools.mcp import _render_tool_result

    assert _render_tool_result({"content": [{"type": "text", "text": "ok"}]}) == "ok"
