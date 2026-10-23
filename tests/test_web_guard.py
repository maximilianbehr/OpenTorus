"""Web fetch hardening (items 6 and 6e): SSRF per hop, byte cap, refusals, egress."""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from opentorus.research.sources.base import (
    AccessDeniedError,
    BlockedDestinationError,
    SourceError,
    http_get_text,
)
from opentorus.tools import netguard, web


class _Handler(BaseHTTPRequestHandler):
    hits: dict[str, int] = {}

    def log_message(self, *args: object) -> None:  # silence
        pass

    def _send(self, code: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        port = self.server.server_address[1]
        _Handler.hits[self.path] = _Handler.hits.get(self.path, 0) + 1
        if self.path == "/page":
            self._send(200, b"<html><title>T</title><p>hello page</p></html>")
        elif self.path == "/big":
            self._send(200, b"a" * 200_000)
        elif self.path == "/to-localhost":
            self._send(302, b"", {"Location": f"http://localhost:{port}/page"})
        elif self.path == "/to-mapped":
            self._send(302, b"", {"Location": f"http://[::ffff:127.0.0.1]:{port}/page"})
        elif self.path == "/to-self":
            self._send(302, b"", {"Location": f"http://127.0.0.1:{port}/page"})
        elif self.path == "/to-gate":
            self._send(302, b"", {"Location": f"http://127.0.0.1:{port}/gate.html"})
        elif self.path == "/to-file":
            self._send(302, b"", {"Location": "file:///etc/passwd"})
        elif self.path == "/captcha":
            self._send(
                403,
                b"<html><title>Just a moment...</title><div class='cf-chl-widget'></div></html>",
            )
        elif self.path == "/captcha200":
            self._send(200, b"<html><div class='g-recaptcha' data-sitekey='x'></div></html>")
        elif self.path == "/ratelimited":
            self._send(429, b"slow down", {"Retry-After": "1"})
        elif self.path == "/flaky":
            if _Handler.hits[self.path] == 1:
                self._send(429, b"slow down", {"Retry-After": "1"})
            else:
                self._send(200, b"recovered")
        elif self.path == "/discusses-captcha":
            self._send(200, b"<p>" + b"An essay about captchas. " * 4000 + b"g-recaptcha</p>")
        else:
            self._send(404, b"nope")


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.hits = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netguard, "sleep", lambda seconds: None)


LOCAL = ("127.0.0.1",)


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "255.255.255.255",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "2002:7f00:0001::",
        "ff02::1",
    ],
)
def test_internal_addresses_are_refused(addr: str) -> None:
    assert netguard.is_internal_ip(ipaddress.ip_address(addr))


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "93.184.216.34"])
def test_public_addresses_are_allowed(addr: str) -> None:
    assert not netguard.is_internal_ip(ipaddress.ip_address(addr))


def test_loopback_url_is_refused_by_default(server: str) -> None:
    with pytest.raises(BlockedDestinationError, match="internal address"):
        http_get_text(f"{server}/page")
    with pytest.raises(SourceError, match="internal address"):
        web.fetch_url(f"{server}/page")


def test_localhost_name_is_refused_after_resolution(server: str) -> None:
    port = server.rsplit(":", 1)[1]
    with pytest.raises(BlockedDestinationError):
        http_get_text(f"http://localhost:{port}/page")


def test_explicitly_allowed_local_host_works(server: str) -> None:
    title, text, truncated = web.fetch_url(f"{server}/page", allow_hosts=LOCAL)
    assert title == "T" and "hello page" in text and not truncated


def test_every_redirect_hop_is_checked(server: str) -> None:
    # The first hop is allowed; the redirect target resolves inward and is refused.
    with pytest.raises(BlockedDestinationError):
        http_get_text(f"{server}/to-localhost", allow_hosts=LOCAL)
    with pytest.raises(BlockedDestinationError):
        http_get_text(f"{server}/to-mapped", allow_hosts=LOCAL)
    assert "hello page" in http_get_text(f"{server}/to-self", allow_hosts=LOCAL)


def test_redirect_to_non_http_is_refused(server: str) -> None:
    with pytest.raises(SourceError, match="not allowed|non-http"):
        http_get_text(f"{server}/to-file", allow_hosts=LOCAL)


def test_redirect_to_human_gate_is_access_denied(server: str) -> None:
    with pytest.raises(AccessDeniedError, match="do not work around"):
        http_get_text(f"{server}/to-gate", allow_hosts=LOCAL)


def test_body_is_capped_while_streaming(server: str) -> None:
    _, text, truncated = web.fetch_url(
        f"{server}/big", allow_hosts=LOCAL, max_bytes=1000, max_chars=10_000_000
    )
    assert truncated is False  # char cap not hit ...
    assert len(text) <= 1000  # ... but the byte cap was
    with pytest.raises(SourceError, match="exceeds 1000 bytes"):
        http_get_text(f"{server}/big", allow_hosts=LOCAL, max_bytes=1000)


def test_challenge_page_is_access_denied(server: str) -> None:
    with pytest.raises(AccessDeniedError) as exc:
        http_get_text(f"{server}/captcha", allow_hosts=LOCAL)
    assert exc.value.status == 403
    assert "do not retry" in str(exc.value)
    with pytest.raises(SourceError, match="Access denied"):
        web.fetch_url(f"{server}/captcha200", allow_hosts=LOCAL)


def test_page_merely_discussing_captchas_is_content(server: str) -> None:
    _, text, _ = web.fetch_url(f"{server}/discusses-captcha", allow_hosts=LOCAL, max_chars=50)
    assert "captchas" in text


def test_429_honours_retry_after_once_then_denies(server: str) -> None:
    assert http_get_text(f"{server}/flaky", allow_hosts=LOCAL) == "recovered"
    assert _Handler.hits["/flaky"] == 2
    with pytest.raises(AccessDeniedError) as exc:
        http_get_text(f"{server}/ratelimited", allow_hosts=LOCAL)
    assert exc.value.status == 429
    assert _Handler.hits["/ratelimited"] == 2  # one wait, one retry, then a refusal


def test_url_credentials_are_refused() -> None:
    with pytest.raises(SourceError, match="credentials"):
        web.fetch_url("https://user:pass@example.org/")


class _Guard:
    def __init__(self, deny: str | None = None) -> None:
        self.seen: list[str] = []
        self.deny = deny

    def authorize(self, url: str) -> str:
        from opentorus.research.egress import EgressBlocked

        self.seen.append(url)
        if self.deny and self.deny in url:
            raise EgressBlocked("denied by test")
        return url


def test_fetch_url_authorizes_every_hop_with_the_egress_guard(server: str) -> None:
    guard = _Guard()
    web.fetch_url(f"{server}/to-self", allow_hosts=LOCAL, egress=guard)
    assert guard.seen == [f"{server}/to-self", f"{server}/page"]
    with pytest.raises(SourceError, match="egress denied"):
        web.fetch_url(f"{server}/page", allow_hosts=LOCAL, egress=_Guard(deny="/page"))


def test_fetch_url_tool_uses_the_egress_guard(server: str, tmp_path) -> None:  # noqa: ANN001
    from opentorus.config import default_config
    from opentorus.tools.base import ToolCall
    from opentorus.tools.builtin import FetchUrlTool

    config = default_config()
    config.permissions.mode = "safe"  # egress forbidden
    config.tools.web.allow_private_hosts = list(LOCAL)
    tool = FetchUrlTool(config=config, ot_dir=tmp_path)
    result = tool.run(ToolCall(name="fetch_url", args={"url": f"{server}/page"}))
    assert not result.ok and "egress denied" in result.content.lower()
    config.permissions.mode = "trusted"
    result = tool.run(ToolCall(name="fetch_url", args={"url": f"{server}/page"}))
    assert result.ok, result.content
    assert (tmp_path / "egress.json").is_file()  # counted against the budget ledger
