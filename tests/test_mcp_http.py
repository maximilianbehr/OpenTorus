"""MCP Streamable HTTP transport (item 21), against a local fake server.

The live LMFDB check is opt-in: ``pytest -m integration tests/test_mcp_http.py``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from opentorus.config import McpServerConfig, default_config
from opentorus.tools.base import ToolCall
from opentorus.tools.mcp import McpError, close_all_mcp_servers, discover_mcp_tools
from opentorus.tools.mcp_http import HttpTransport, validate_url

_TOOLS = [
    {"name": "search", "description": "search", "inputSchema": {"type": "object"}},
    {"name": "slow", "description": "slow", "inputSchema": {"type": "object"}},
]


class _Fake(BaseHTTPRequestHandler):
    seen: list[dict] = []
    deleted: list[str] = []

    def log_message(self, *args: object) -> None:
        pass

    def _reply(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self) -> None:  # noqa: N802
        _Fake.deleted.append(self.headers.get("Mcp-Session-Id", ""))
        self._reply(200, b"", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        message = json.loads(self.rfile.read(length))
        _Fake.seen.append(
            {
                "method": message.get("method"),
                "session": self.headers.get("Mcp-Session-Id"),
                "accept": self.headers.get("Accept"),
                "version": self.headers.get("MCP-Protocol-Version"),
            }
        )
        if "id" not in message:
            self._reply(202, b"", "text/plain")
            return
        rid = message["id"]
        method = message["method"]
        if method == "initialize":
            body = {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-03-26"}}
            self._reply(
                200, json.dumps(body).encode(), "application/json", {"Mcp-Session-Id": "s-1"}
            )
        elif method == "tools/list":
            body = {"jsonrpc": "2.0", "id": rid, "result": {"tools": _TOOLS}}
            self._reply(200, json.dumps(body).encode(), "application/json")
        elif method == "tools/call":
            name = message["params"]["name"]
            if name == "slow":
                import time

                time.sleep(3)
            note = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
            result = {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"content": [{"type": "text", "text": f"found {message['params']}"}]},
            }
            stream = (
                ": keep-alive\n\n"
                f"data: {json.dumps(note)}\n\n"
                f"event: message\ndata: {json.dumps(result)}\n\n"
            )
            self._reply(200, stream.encode(), "text/event-stream")
        else:
            self._reply(404, b"", "text/plain")


@pytest.fixture
def server() -> Iterator[str]:
    _Fake.seen, _Fake.deleted = [], []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
    finally:
        close_all_mcp_servers()
        httpd.shutdown()
        httpd.server_close()


def _config(url: str, *, mode: str = "trusted", **extra: object):  # noqa: ANN202
    config = default_config()
    config.permissions.mode = mode  # type: ignore[assignment]
    config.tools.mcp = [
        McpServerConfig(name="fake", transport="http", url=url, enabled=True, **extra)
    ]
    return config


def test_http_server_tools_are_discovered_and_called(server: str, tmp_path) -> None:  # noqa: ANN001
    tools = {t.remote_name: t for t in discover_mcp_tools(_config(server), tmp_path)}
    assert sorted(tools) == ["search", "slow"]
    result = tools["search"].run(ToolCall(name="mcp__fake__search", args={"q": "elliptic"}))
    assert result.ok, result.content
    assert "elliptic" in result.content  # read from the SSE stream, notification skipped
    methods = [s["method"] for s in _Fake.seen]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert _Fake.seen[0]["session"] is None
    assert all(s["session"] == "s-1" for s in _Fake.seen[1:])  # Mcp-Session-Id echoed
    assert all("text/event-stream" in (s["accept"] or "") for s in _Fake.seen)
    assert _Fake.seen[-1]["version"] == "2025-03-26"
    close_all_mcp_servers()
    assert _Fake.deleted == ["s-1"]  # the session is ended on close


def test_http_calls_go_through_the_egress_guard(server: str, tmp_path) -> None:  # noqa: ANN001
    # Safe mode forbids egress: discovery cannot even list tools.
    assert discover_mcp_tools(_config(server, mode="safe"), tmp_path) == []
    assert _Fake.seen == []
    tools = discover_mcp_tools(_config(server), tmp_path)
    assert tools
    ledger = json.loads((tmp_path / "egress.json").read_text())
    assert ledger["count"] >= 3  # every POST is counted against the budget


def test_secret_in_arguments_is_blocked_before_sending(server: str, tmp_path) -> None:  # noqa: ANN001
    tools = {t.remote_name: t for t in discover_mcp_tools(_config(server), tmp_path)}
    before = len(_Fake.seen)
    key = "sk-" + "abcdefghijklmnopqrstuvwxyz012345"
    result = tools["search"].run(ToolCall(name="mcp__fake__search", args={"q": key}))
    assert not result.ok and "blocked" in result.content.lower()
    assert len(_Fake.seen) == before


def test_http_timeout_is_outcome_unknown(server: str, tmp_path) -> None:  # noqa: ANN001
    tools = {t.remote_name: t for t in discover_mcp_tools(_config(server, timeout=1), tmp_path)}
    result = tools["slow"].run(ToolCall(name="mcp__fake__slow", args={}))
    assert not result.ok and result.metadata["outcome"] == "unknown"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/mcp",  # plain HTTP to a non-loopback host
        "https://user:pw@example.org/mcp",
        "https://example.org/mcp#frag",
        "ftp://example.org/mcp",
    ],
)
def test_invalid_urls_are_refused(url: str) -> None:
    with pytest.raises(McpError):
        validate_url(url)


def test_reserved_headers_cannot_be_overridden() -> None:
    with pytest.raises(McpError, match="Reserved"):
        HttpTransport("https://example.org/mcp", headers={"Mcp-Session-Id": "forged"})


@pytest.mark.integration
def test_lmfdb_mcp_lists_tools(tmp_path) -> None:  # noqa: ANN001
    config = _config("https://mcp.lmfdb.org/mcp")
    tools = discover_mcp_tools(config, tmp_path)
    assert tools, "LMFDB MCP server listed no tools"
