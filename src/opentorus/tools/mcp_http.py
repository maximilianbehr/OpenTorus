"""MCP Streamable HTTP transport (JSON-RPC over HTTP POST, optional SSE replies).

The second MCP transport next to stdio (:mod:`opentorus.tools.mcp`). Each
JSON-RPC message is one ``POST`` to the configured endpoint; the server answers
with ``application/json`` (one message or a batch) or ``text/event-stream``
(server-sent events, each ``data:`` a JSON-RPC message), and may assign a session
with the ``Mcp-Session-Id`` header, echoed on every later request and ended with
a ``DELETE`` on close.

Gated like any network access:

* the tool call itself passes the external-tool permission in the agent loop;
* every request is authorized by the :class:`~opentorus.research.egress.EgressGuard`
  (host consent, rate limit, daily budget) and its body screened by the pre-egress
  DLP (a secret in the arguments blocks the send);
* HTTPS only -- plain HTTP only to a loopback IP literal; no userinfo, no fragment,
  no ambient proxies, **no redirects**, no retries, no session recovery;
* every message is bounded to 1 MiB and every response to a deadline; a request
  that times out has an unknown outcome and is not retried.

Headers that carry the transport (``accept``, ``content-type``,
``mcp-session-id``, ``mcp-protocol-version``) cannot be overridden by config.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from opentorus.tools.mcp import MAX_MESSAGE_BYTES, McpError, McpTimeout

_PROTOCOL_VERSION = "2025-03-26"
_RESERVED_HEADERS = frozenset(
    {"accept", "content-type", "mcp-session-id", "mcp-protocol-version", "content-length", "host"}
)
_MAX_RESPONSE_BYTES = 16 * MAX_MESSAGE_BYTES


def validate_url(url: str) -> str:
    """HTTPS, or HTTP to a loopback IP literal; no userinfo or fragment."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").strip("[]")
    loopback = False
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if (
        not host
        or not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise McpError(
            "MCP URL requires HTTPS (HTTP only for a loopback IP), no userinfo or fragment: "
            f"{url!r}"
        )
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        raise urllib.error.HTTPError(
            req.full_url, code, f"MCP endpoint redirected to {newurl!r}; refused", headers, fp
        )


def _opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        _NoRedirect(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


class HttpTransport:
    """One MCP server over Streamable HTTP."""

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        egress: Any | None = None,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
    ) -> None:
        self.url = validate_url(url)
        extra = dict(headers or {})
        bad = [k for k in extra if k.lower() in _RESERVED_HEADERS]
        if bad:
            raise McpError(f"Reserved MCP HTTP header(s) in config: {', '.join(sorted(bad))}.")
        self.headers = extra
        self.egress = egress
        self.max_message_bytes = max_message_bytes
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self._open = False
        self._opener = _opener()

    @property
    def alive(self) -> bool:
        return self._open

    def start(self) -> None:
        self._open = True

    # -- plumbing ------------------------------------------------------------------

    def _authorize(self, body: bytes) -> None:
        if self.egress is None:
            return
        from opentorus.research.egress import EgressBlocked

        try:
            self.egress.authorize(self.url)
            self.egress.screen_payload(body.decode("utf-8", errors="replace"))
        except EgressBlocked as exc:
            raise McpError(f"Network egress denied: {exc}") from exc
        except Exception as exc:  # DlpBlocked and friends: fail closed
            raise McpError(f"MCP request blocked: {exc}") from exc

    def _headers(self) -> dict[str, str]:
        out = {
            **self.headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "OpenTorus-MCP/0.1",
        }
        if self.session_id:
            out["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            out["MCP-Protocol-Version"] = self.protocol_version
        return out

    def _post(self, payload: dict, timeout: float):  # noqa: ANN202
        body = json.dumps(payload).encode("utf-8")
        if len(body) > self.max_message_bytes:
            raise McpError("MCP request exceeds the 1 MiB bound.")
        self._authorize(body)
        request = urllib.request.Request(
            self.url, data=body, method="POST", headers=self._headers()
        )
        try:
            return self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and self.session_id:
                self._open = False
                raise McpError("MCP HTTP session expired (404); not recovered.") from exc
            raise McpError(f"MCP HTTP {exc.code}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise McpTimeout(f"MCP HTTP request got no answer within {timeout:g}s.") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError | socket.timeout):
                raise McpTimeout(f"MCP HTTP request got no answer within {timeout:g}s.") from exc
            raise McpError(f"Could not reach MCP server: {exc.reason}") from exc

    def _read_json(self, response, deadline: float) -> list[dict]:  # noqa: ANN001
        data = response.read(self.max_message_bytes + 1)
        if len(data) > self.max_message_bytes:
            raise McpError("MCP message exceeds the 1 MiB bound.")
        try:
            parsed = json.loads(data.decode("utf-8")) if data.strip() else []
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise McpError(f"MCP server sent invalid JSON: {exc}") from exc
        items = parsed if isinstance(parsed, list) else [parsed]
        return [m for m in items if isinstance(m, dict)]

    def _sse_messages(self, response, deadline: float, request_id: int) -> dict | None:  # noqa: ANN001
        total = 0
        event: list[str] = []
        size = 0
        while True:
            if time.monotonic() > deadline:
                raise McpTimeout("MCP SSE stream did not answer in time.")
            try:
                raw = response.readline(self.max_message_bytes + 2)
            except TimeoutError as exc:
                raise McpTimeout("MCP SSE stream did not answer in time.") from exc
            if not raw:
                return None
            total += len(raw)
            if total > _MAX_RESPONSE_BYTES:
                raise McpError("MCP SSE response exceeds its bound.")
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                if event:
                    message = self._parse_event("\n".join(event))
                    event, size = [], 0
                    if message is not None and message.get("id") == request_id:
                        return message
                continue
            if line.startswith(":"):
                continue  # comment / keep-alive
            field, _, value = line.partition(":")
            if field == "data":
                value = value[1:] if value.startswith(" ") else value
                size += len(value)
                if size > self.max_message_bytes:
                    raise McpError("MCP message exceeds the 1 MiB bound.")
                event.append(value)

    @staticmethod
    def _parse_event(data: str) -> dict | None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            return None
        if not isinstance(message, dict) or ("method" in message and "id" in message):
            return None  # not a response (server-initiated requests are not supported)
        return message

    # -- transport API -------------------------------------------------------------

    def request(self, method: str, params: dict, timeout: float, *, request_id: int) -> dict:
        if not self._open:
            raise McpError("MCP HTTP transport is closed.")
        deadline = time.monotonic() + timeout
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        with self._post(payload, timeout) as response:
            session = response.headers.get("Mcp-Session-Id")
            if method == "initialize" and session:
                if len(session) > 256 or not session.isprintable():
                    raise McpError("Invalid MCP session header.")
                self.session_id = session
            ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            try:
                if ctype == "text/event-stream":
                    message = self._sse_messages(response, deadline, request_id)
                else:
                    message = next(
                        (
                            m
                            for m in self._read_json(response, deadline)
                            if m.get("id") == request_id
                        ),
                        None,
                    )
            except TimeoutError as exc:
                raise McpTimeout(f"MCP '{method}' got no answer within {timeout:g}s.") from exc
        if message is None:
            raise McpError(f"MCP server sent no response to '{method}'.")
        if method == "initialize":
            result = message.get("result")
            version = result.get("protocolVersion") if isinstance(result, dict) else None
            self.protocol_version = str(version) if version else _PROTOCOL_VERSION
        return message

    def notify(self, method: str, params: dict) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        with self._post(payload, 30.0) as response:
            response.read(self.max_message_bytes)

    def close(self) -> None:
        if not self._open:
            return
        self._open = False
        if not self.session_id:
            return
        request = urllib.request.Request(self.url, method="DELETE", headers=self._headers())
        try:
            with self._opener.open(request, timeout=5):
                pass
        except (OSError, urllib.error.URLError):
            pass  # best effort; 404/405 count as done
        finally:
            self.session_id = None
