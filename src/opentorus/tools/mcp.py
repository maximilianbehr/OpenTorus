"""External tool plugins via the Model-Context-Protocol (MCP).

OpenTorus can surface tools from external MCP servers through the same
``ToolRegistry`` / ``Tool`` interface as built-in tools, so the agent loop and
permission policy treat them uniformly. Plugins are strictly opt-in: nothing
connects unless a server is configured *and* enabled in ``config.tools.mcp``.

The client speaks the minimal subset of MCP we need over stdio JSON-RPC:
``initialize``, ``tools/list``, and ``tools/call``. It uses only the standard
library so no extra dependency is required. Every external tool call is gated by
``permissions.policy.evaluate_external_tool`` in the agent loop, exactly like a
shell command -- an external tool can never bypass the safety policy.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from opentorus.config import Config, McpServerConfig
from opentorus.tools.base import Tool, ToolCall, ToolResult
from opentorus.tools.registry import ToolRegistry

logger = logging.getLogger("opentorus")

_PROTOCOL_VERSION = "2024-11-05"

# Cap the size of a flattened MCP result fed back into the model context. A remote
# server is untrusted and could otherwise inject an unbounded payload (built-in
# fetch_url/web_search are capped the same way).
_MCP_RESULT_MAX_CHARS = 8000


class McpError(RuntimeError):
    """Raised when an MCP server cannot be reached or returns an error."""


class McpClient:
    """A minimal stdio JSON-RPC client for a single MCP server."""

    def __init__(self, command: str, args: list[str] | None = None, timeout: float = 30.0) -> None:
        self.command = command
        self.args = args or []
        self.timeout = timeout
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0

    def __enter__(self) -> McpClient:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            raise McpError(f"Could not start MCP server '{self.command}': {exc}") from exc
        self._request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "opentorus", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()
        finally:
            self._proc = None

    def list_tools(self) -> list[dict]:
        result = self._request("tools/list", {})
        return list(result.get("tools", []))

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        return _render_tool_result(result)

    def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise McpError("MCP server is not running.")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict) -> dict:
        if self._proc is None or self._proc.stdout is None:
            raise McpError("MCP server is not running.")
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        # Read lines until we see the response with our id (skip notifications).
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise McpError(f"MCP server closed the connection during '{method}'.")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                err = message["error"]
                raise McpError(f"MCP '{method}' failed: {err.get('message', err)}")
            return message.get("result", {})


def _render_tool_result(result: dict) -> str:
    """Flatten an MCP ``tools/call`` result into plain text for the agent loop."""
    parts: list[str] = []
    for block in result.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, dict):
            parts.append(json.dumps(block))
    text = "\n".join(p for p in parts if p)
    if len(text) > _MCP_RESULT_MAX_CHARS:
        omitted = len(text) - _MCP_RESULT_MAX_CHARS
        text = text[:_MCP_RESULT_MAX_CHARS] + f"\n…[truncated {omitted} chars of MCP output]"
    if result.get("isError"):
        return f"[tool error] {text}" if text else "[tool error]"
    return text


class McpTool(Tool):
    """Wraps a single remote MCP tool as an OpenTorus tool.

    The tool name is namespaced (``mcp__<server>__<tool>``) to avoid clashes with
    built-ins. Its permission kind is ``external`` so the loop routes it through
    ``evaluate_external_tool``.
    """

    permission = "external"
    risk_level = "medium"

    def __init__(self, server: str, spec: dict, client_factory) -> None:
        remote = spec.get("name", "")
        self.remote_name = remote
        self.server = server
        self.name = f"mcp__{server}__{remote}"
        self.description = spec.get("description", f"External MCP tool '{remote}'.")
        self.input_schema = spec.get("inputSchema") or {"type": "object", "properties": {}}
        self._client_factory = client_factory

    def run(self, call: ToolCall) -> ToolResult:
        try:
            with self._client_factory() as client:
                output = client.call_tool(self.remote_name, call.args)
        except McpError as exc:
            return self.fail(call, f"MCP error: {exc}")
        return self.ok(call, output, server=self.server, remote_tool=self.remote_name)


def _make_factory(server: McpServerConfig):
    def factory() -> McpClient:
        return McpClient(server.command, server.args)

    return factory


def discover_mcp_tools(config: Config) -> list[McpTool]:
    """Connect to each enabled MCP server and return wrapped tools.

    Servers that fail to start are skipped with a warning so a broken plugin
    never breaks the session.
    """
    tools: list[McpTool] = []
    for server in config.tools.mcp:
        if not server.enabled:
            continue
        factory = _make_factory(server)
        try:
            with factory() as client:
                specs = client.list_tools()
        except McpError as exc:
            logger.warning("Skipping MCP server '%s': %s", server.name, exc)
            continue
        for spec in specs:
            tools.append(McpTool(server.name, spec, factory))
    return tools


def register_mcp_tools(registry: ToolRegistry, config: Config) -> list[str]:
    """Register all enabled MCP tools into ``registry``. Returns the tool names."""
    names: list[str] = []
    for tool in discover_mcp_tools(config):
        try:
            registry.register(tool)
        except ValueError:
            logger.warning("MCP tool '%s' clashes with an existing tool; skipping.", tool.name)
            continue
        names.append(tool.name)
    return names
