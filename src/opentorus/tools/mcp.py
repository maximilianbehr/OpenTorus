"""External tool plugins via the Model-Context-Protocol (MCP).

OpenTorus can surface tools from external MCP servers through the same
``ToolRegistry`` / ``Tool`` interface as built-in tools, so the agent loop and
permission policy treat them uniformly. Plugins are strictly opt-in: nothing
connects unless a server is configured *and* enabled in ``config.tools.mcp``.

The client speaks the subset of MCP we need -- ``initialize``, ``tools/list`` and
``tools/call`` -- over one of two transports, using only the standard library:

* ``stdio`` (:class:`StdioTransport`): the server is a child process. It gets a
  clean environment (the allowlist from :mod:`opentorus.tools.childenv`; no API key
  from this process ever reaches it) plus exactly the ``env`` configured for that
  server. It runs in its own process group and lives for the session: one process
  per server, started at discovery, reused by every call, killed on exit.
* ``http`` (:mod:`opentorus.tools.mcp_http`): MCP Streamable HTTP, gated by the
  external-tool permission and the egress guard.

Every read is bounded in time (``timeout`` per server) and size (1 MiB per
message). A call whose answer does not arrive in time has an **unknown outcome**:
it may have taken effect. It is reported as such, recorded in the intent log, and
never retried automatically. A per-server ``tools`` allowlist exposes only the
named tools and fails startup if the server does not offer one of them.

Every external tool call is gated by ``permissions.policy.evaluate_external_tool``
in the agent loop, exactly like a shell command -- an external tool can never
bypass the safety policy.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from opentorus.config import Config, McpServerConfig
from opentorus.errors import OpenTorusError
from opentorus.tools.base import Tool, ToolCall, ToolResult
from opentorus.tools.registry import ToolRegistry

logger = logging.getLogger("opentorus")

_PROTOCOL_VERSION = "2024-11-05"

# Cap the size of a flattened MCP result fed back into the model context. A remote
# server is untrusted and could otherwise inject an unbounded payload (built-in
# fetch_url/web_search are capped the same way).
_MCP_RESULT_MAX_CHARS = 8000
# Hard bound on one JSON-RPC message read from a server, before parsing.
MAX_MESSAGE_BYTES = 1 << 20


class McpError(RuntimeError):
    """Raised when an MCP server cannot be reached or returns an error."""


class McpTimeout(McpError):
    """No answer in time: the request may or may not have taken effect."""


class McpConfigError(OpenTorusError):
    """A configured MCP server does not match its configuration (e.g. allowlist)."""


class McpTransport(Protocol):
    def start(self) -> None: ...

    def request(self, method: str, params: dict, timeout: float, *, request_id: int) -> dict: ...

    def notify(self, method: str, params: dict) -> None: ...

    def close(self) -> None: ...

    @property
    def alive(self) -> bool: ...


def _server_env(extra: dict[str, str] | None) -> dict[str, str]:
    """Clean allowlist env plus exactly what the server's config names."""
    from opentorus.tools.childenv import clean_env

    env = clean_env()
    env.update(extra or {})
    return env


class StdioTransport:
    """JSON-RPC over a child process's stdin/stdout, one JSON message per line."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
    ) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.max_message_bytes = max_message_bytes
        self._proc: subprocess.Popen[bytes] | None = None
        self._inbox: queue.Queue[dict | BaseException] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._broken = False

    @property
    def alive(self) -> bool:
        return not self._broken and self._proc is not None and self._proc.poll() is None

    def _fail_stream(self, message: str) -> None:
        # The stream can no longer be trusted to stay in sync; the handle replaces
        # this transport (and its process) on the next call.
        self._broken = True
        self._inbox.put(McpError(message))

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=_server_env(self.env),
                start_new_session=os.name != "nt",
            )
        except (OSError, ValueError) as exc:
            raise McpError(f"Could not start MCP server '{self.command}': {exc}") from exc
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        stream = proc.stdout
        buf = bytearray()
        try:
            while True:
                chunk = stream.read1(65536)  # type: ignore[attr-defined]
                if not chunk:
                    self._fail_stream("MCP server closed the connection.")
                    return
                buf.extend(chunk)
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    line = bytes(buf[:nl])
                    del buf[: nl + 1]
                    if len(line) > self.max_message_bytes:
                        self._fail_stream("MCP message exceeds the 1 MiB bound.")
                        return
                    self._dispatch(line)
                if len(buf) > self.max_message_bytes:
                    self._fail_stream("MCP message exceeds the 1 MiB bound.")
                    return
        except (OSError, ValueError) as exc:
            self._fail_stream(f"MCP read failed: {exc}")

    def _dispatch(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(message, dict):
            return
        if "method" in message and "id" in message:
            # A server-initiated request (sampling, roots, ping). We offer none of
            # these capabilities; answer so the server does not wait on us.
            if message.get("method") == "ping":
                self._write({"jsonrpc": "2.0", "id": message["id"], "result": {}})
            else:
                self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32601, "message": "Not supported by this client."},
                    }
                )
            return
        if "id" in message:
            self._inbox.put(message)

    def _write(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpError("MCP server is not running.")
        data = (json.dumps(payload) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                proc.stdin.write(data)
                proc.stdin.flush()
            except (OSError, ValueError) as exc:
                raise McpError(f"MCP server is not accepting input: {exc}") from exc

    def notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, timeout: float, *, request_id: int) -> dict:
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpTimeout(
                    f"MCP '{method}' got no answer within {timeout:g}s; outcome unknown."
                )
            try:
                item = self._inbox.get(timeout=remaining)
            except queue.Empty:
                continue
            except BaseException:
                # A cancel while waiting: the server may be mid-effect; end it.
                self.close()
                raise
            if isinstance(item, McpError):
                self._inbox.put(item)  # sticky: later requests fail the same way
                raise item
            if isinstance(item, BaseException):
                self.close()
                raise item
            if item.get("id") != request_id:
                continue  # a late answer to an earlier, timed-out request
            return item

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        if os.name != "nt":
            from opentorus.tools.shell import terminate_process_group

            try:
                terminate_process_group(proc, grace=2.0)
            except OSError:
                pass
        else:  # pragma: no cover - POSIX CI
            proc.kill()
            proc.wait()
        try:
            if proc.stdout:
                proc.stdout.close()
        except OSError:
            pass


class McpClient:
    """A JSON-RPC client for one MCP server (stdio by default)."""

    def __init__(
        self,
        command: str = "",
        args: list[str] | None = None,
        timeout: float = 30.0,
        *,
        env: dict[str, str] | None = None,
        transport: Any | None = None,
    ) -> None:
        self.command = command
        self.args = args or []
        self.timeout = timeout
        self._transport = transport or StdioTransport(command, self.args, env=env)
        self._next_id = 0
        self._lock = threading.Lock()
        self._started = False

    def __enter__(self) -> McpClient:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def alive(self) -> bool:
        return self._started and self._transport.alive

    def start(self) -> None:
        self._transport.start()
        self._started = True
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "opentorus", "version": "0.1.0"},
                },
            )
            self._transport.notify("notifications/initialized", {})
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self._started = False
        self._transport.close()

    def list_tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor: str | None = None
        for _ in range(50):  # paging bound
            params: dict = {"cursor": cursor} if cursor else {}
            result = self._request("tools/list", params)
            tools.extend(t for t in result.get("tools", []) if isinstance(t, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        return _render_tool_result(result)

    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            message = self._transport.request(method, params, self.timeout, request_id=request_id)
        if "error" in message:
            err = message["error"]
            detail = err.get("message", err) if isinstance(err, dict) else err
            raise McpError(f"MCP '{method}' failed: {detail}")
        result = message.get("result", {})
        return result if isinstance(result, dict) else {}


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


# --- session-scoped server handles -----------------------------------------------


_LIVE: set[McpServerHandle] = set()
_LIVE_LOCK = threading.Lock()


def close_all_mcp_servers() -> None:
    """Stop every MCP server this process started (also runs at interpreter exit)."""
    with _LIVE_LOCK:
        handles = list(_LIVE)
    for handle in handles:
        handle.close()


atexit.register(close_all_mcp_servers)


class McpServerHandle:
    """One running MCP server shared by all of its tools for the session."""

    def __init__(self, server: McpServerConfig, *, egress: Any | None = None) -> None:
        self.server = server
        self._egress = egress
        self._client: McpClient | None = None
        self._lock = threading.Lock()

    def _make_client(self) -> McpClient:
        server = self.server
        if server.transport == "http":
            from opentorus.tools.mcp_http import HttpTransport

            if not server.url:
                raise McpError(f"MCP server '{server.name}' uses http but has no 'url'.")
            transport = HttpTransport(server.url, headers=server.headers, egress=self._egress)
            return McpClient(timeout=server.timeout, transport=transport)
        if not server.command:
            raise McpError(f"MCP server '{server.name}' has no 'command'.")
        return McpClient(server.command, server.args, server.timeout, env=server.env)

    def client(self) -> McpClient:
        with self._lock:
            if self._client is None or not self._client.alive:
                if self._client is not None:
                    self._client.close()
                client = self._make_client()
                client.start()
                self._client = client
                with _LIVE_LOCK:
                    _LIVE.add(self)
            return self._client

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
        with _LIVE_LOCK:
            _LIVE.discard(self)
        if client is not None:
            client.close()

    def reset(self) -> None:
        """Drop a client whose stream may be desynchronised (after a timeout)."""
        self.close()


class McpTool(Tool):
    """Wraps a single remote MCP tool as an OpenTorus tool.

    The tool name is namespaced (``mcp__<server>__<tool>``) to avoid clashes with
    built-ins. Its permission kind is ``external`` so the loop routes it through
    ``evaluate_external_tool``.
    """

    permission = "external"
    risk_level = "medium"

    def __init__(
        self,
        server: str,
        spec: dict,
        handle: McpServerHandle | Any,
        *,
        intents: Any | None = None,
    ) -> None:
        remote = spec.get("name", "")
        self.remote_name = remote
        self.server = server
        self.name = f"mcp__{server}__{remote}"
        self.description = spec.get("description", f"External MCP tool '{remote}'.")
        self.input_schema = spec.get("inputSchema") or {"type": "object", "properties": {}}
        # A server's annotations are hints from an untrusted party. They may only
        # make approval *finer* (irreversible -> per call); a read-only hint lets a
        # session approval cover the tool, never skips the permission gate.
        raw_annotations = spec.get("annotations")
        annotations: dict = raw_annotations if isinstance(raw_annotations, dict) else {}
        self.effect = "observation" if annotations.get("readOnlyHint") is True else "irreversible"
        self._handle = handle
        self._intents = intents

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.execution.intents import args_digest, new_operation_id

        op_id = new_operation_id("mcp")
        if self._intents is not None:
            self._intents.intent(
                op_id,
                "mcp_tool_call",
                target=f"{self.server}/{self.remote_name}",
                digest=args_digest(call.args),
            )
        try:
            handle = self._handle
            if isinstance(handle, McpServerHandle):
                output = handle.client().call_tool(self.remote_name, call.args)
            else:  # legacy factory: a context manager per call
                with handle() as client:
                    output = client.call_tool(self.remote_name, call.args)
        except McpTimeout as exc:
            if isinstance(self._handle, McpServerHandle):
                self._handle.reset()
            if self._intents is not None:
                self._intents.outcome(op_id, "unknown", reason=str(exc))
            return self.fail(
                call,
                f"MCP outcome unknown: {exc} The call may or may not have taken effect on "
                f"'{self.server}'. Do not repeat it automatically -- check its effect first "
                f"(operation id {op_id}).",
                server=self.server,
                remote_tool=self.remote_name,
                outcome="unknown",
                op_id=op_id,
            )
        except McpError as exc:
            if self._intents is not None:
                self._intents.outcome(op_id, "failed", reason=str(exc)[:500])
            return self.fail(call, f"MCP error: {exc}", outcome="failed", op_id=op_id)
        if self._intents is not None:
            self._intents.outcome(op_id, "succeeded")
        return self.ok(call, output, server=self.server, remote_tool=self.remote_name, op_id=op_id)


def _egress_for(config: Config, ot_dir: Path | None) -> Any:
    from opentorus.research.egress import EgressGuard

    lit = config.tools.literature
    return EgressGuard(
        config.permissions.mode,
        style=config.agent.style,
        review=config.agent.mode == "review",
        rate_limit_per_minute=lit.rate_limit_per_minute,
        daily_request_budget=lit.daily_request_budget,
        # The call itself was approved at the external-tool gate, which asks in
        # exactly the modes the egress policy would.
        confirm=lambda host: True,
        ledger_path=(ot_dir / "egress.json") if ot_dir is not None else None,
        dlp=config.governance.dlp,
    )


def _select(server: McpServerConfig, specs: list[dict]) -> list[dict]:
    if server.tools is None:
        return specs
    offered = {s.get("name") for s in specs}
    missing = [name for name in server.tools if name not in offered]
    if missing:
        raise McpConfigError(
            f"MCP server '{server.name}' does not offer allowlisted tool(s) "
            f"{', '.join(sorted(missing))}; offered: {', '.join(sorted(map(str, offered)))}. "
            "Fix tools.mcp[].tools or the server."
        )
    wanted = set(server.tools)
    return [s for s in specs if s.get("name") in wanted]


def discover_mcp_tools(config: Config, ot_dir: Path | None = None) -> list[McpTool]:
    """Connect to each enabled MCP server and return wrapped tools.

    Servers that fail to start are skipped with a warning so a broken plugin
    never breaks the session. A server that runs but lacks an allowlisted tool
    is a configuration error and raises :class:`McpConfigError`.
    """
    from opentorus.execution.intents import INTENTS_FILENAME, IntentLog

    intents = IntentLog(ot_dir / INTENTS_FILENAME) if ot_dir is not None else None
    tools: list[McpTool] = []
    for server in config.tools.mcp:
        if not server.enabled:
            continue
        egress = _egress_for(config, ot_dir) if server.transport == "http" else None
        handle = McpServerHandle(server, egress=egress)
        try:
            specs = handle.client().list_tools()
        except McpError as exc:
            handle.close()
            logger.warning("Skipping MCP server '%s': %s", server.name, exc)
            continue
        except Exception as exc:  # noqa: BLE001 — e.g. EgressBlocked
            handle.close()
            logger.warning("Skipping MCP server '%s': %s", server.name, exc)
            continue
        try:
            selected = _select(server, specs)
        except McpConfigError:
            handle.close()
            raise
        for spec in selected:
            tools.append(McpTool(server.name, spec, handle, intents=intents))
    return tools


def register_mcp_tools(
    registry: ToolRegistry, config: Config, ot_dir: Path | None = None
) -> list[str]:
    """Register all enabled MCP tools into ``registry``. Returns the tool names."""
    names: list[str] = []
    for tool in discover_mcp_tools(config, ot_dir):
        try:
            registry.register(tool)
        except ValueError:
            logger.warning("MCP tool '%s' clashes with an existing tool; skipping.", tool.name)
            continue
        names.append(tool.name)
    return names
