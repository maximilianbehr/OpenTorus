"""Guarded HTTP: no internal addresses, bounded bodies, refusals reported as refusals.

Every outbound HTTP(S) request OpenTorus makes for literature, datasets, PDFs and
``fetch_url`` goes through :func:`guarded_open` / :func:`read_capped`:

* **No internal addresses.** The host of *every* hop -- the first request and each
  redirect -- is resolved, every resolved address is checked, and the socket is
  connected to the checked address (so a DNS answer cannot change between check
  and connect). Loopback, private, link-local, shared/CGNAT (100.64/10),
  unspecified, broadcast, multicast and reserved addresses are refused, including
  IPv4 addresses embedded in IPv6 (``::ffff:127.0.0.1``). This is what keeps a
  fetched page from redirecting the agent into a local vLLM/Ollama server or a
  cloud metadata endpoint. Hosts named in ``tools.web.allow_private_hosts`` are
  exempt -- an explicit, configured choice.
* **No ambient proxies**, at most five redirects, http(s) only.
* **Bounded bodies.** The body is streamed and reading stops at the cap.
* **A site's refusal is a refusal.** A captcha / Cloudflare challenge, a redirect
  to a human gate, or a 429 raises :class:`AccessDenied` whose message says not
  to work around it. A 429/503 with a short ``Retry-After`` is waited out once.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable

MAX_REDIRECTS = 5
# Longest Retry-After honoured (seconds); longer ones are reported, not waited.
MAX_RETRY_AFTER = 30.0

# Challenge marks, searched only in small HTML bodies so an ordinary page that
# discusses captchas stays content (after open-math-harness program-files/web).
_CHALLENGE_PAGES = (
    "cf-chl-",
    "challenge-platform",
    "cf_chl_opt",
    "<title>just a moment...</title>",
    "attention required! | cloudflare",
)
_CAPTCHAS = ("g-recaptcha", "h-captcha", "hcaptcha.com/1/api.js", "recaptcha/api.js")
_CHALLENGE_SCAN_LIMIT = 64 * 1024
_GATE_SEGMENT = re.compile(r"(?:^|/)(?:gate(?:\.html?)?|[^/]*captcha[^/]*)(?:/|$)", re.I)


class BlockedAddress(OSError):
    """The destination resolves to an internal address."""


class AccessDenied(Exception):
    """The site refused (captcha, challenge, human gate, 429). Do not work around it."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def denial_message(url: str, why: str) -> str:
    host = urllib.parse.urlparse(url).hostname or url
    return (
        f"Access denied by {host}: {why}. This is the site's decision -- do not retry "
        "it, and do not work around it (another user agent, a cookie, a mirror, a "
        "proxy, or a shell command that fetches the same page)."
    )


def is_internal_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address that is not a public unicast address."""
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if mapped is not None:
            return is_internal_ip(mapped)
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local:
        return True
    if ip.is_private or ip.is_reserved:
        return True
    # 100.64.0.0/10 (shared/CGNAT) and the like are neither private nor global.
    return not ip.is_global


def _host_allowed(host: str, allow_hosts: Iterable[str]) -> bool:
    h = host.strip("[]").rstrip(".").lower()
    return any(h == a.strip("[]").rstrip(".").lower() for a in allow_hosts)


def check_host(host: str, port: int, allow_hosts: Iterable[str] = ()) -> list[tuple]:
    """Resolve ``host`` and return its addresses, refusing any internal one."""
    allowed = _host_allowed(host, allow_hosts)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OSError(f"Could not resolve {host}: {exc}") from exc
    if not allowed:
        for info in infos:
            addr = str(info[4][0])
            try:
                ip = ipaddress.ip_address(addr.split("%", 1)[0])
            except ValueError:
                raise BlockedAddress(f"refusing unparseable address {addr!r} for {host}") from None
            if is_internal_ip(ip):
                raise BlockedAddress(
                    f"refusing to reach {host}: it resolves to the internal address {ip} "
                    "(loopback/private/link-local addresses are never fetched; add the host "
                    "to tools.web.allow_private_hosts to allow it explicitly)"
                )
    return infos


def _guarded_create_connection(allow_hosts: tuple[str, ...]) -> Callable:
    def create(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):  # noqa: ANN001, ANN202
        host, port = address
        infos = check_host(host, port, allow_hosts)
        last: OSError | None = None
        for family, socktype, proto, _canon, sockaddr in infos:
            sock = socket.socket(family, socktype, proto)
            try:
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                if source_address:
                    sock.bind(source_address)
                sock.connect(sockaddr)  # the checked address, not a fresh lookup
                return sock
            except OSError as exc:
                last = exc
                sock.close()
        raise last or OSError(f"Could not connect to {host}")

    return create


def _connection_classes(allow_hosts: tuple[str, ...]):  # noqa: ANN202
    creator = _guarded_create_connection(allow_hosts)

    class GuardedHTTPConnection(http.client.HTTPConnection):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            self._create_connection = creator

    class GuardedHTTPSConnection(http.client.HTTPSConnection):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            self._create_connection = creator

    return GuardedHTTPConnection, GuardedHTTPSConnection


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def __init__(self, on_redirect: Callable[[str], object] | None) -> None:
        super().__init__()
        self._on_redirect = on_redirect

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme not in ("http", "https"):
            raise urllib.error.HTTPError(
                newurl, code, f"refusing redirect to non-http(s) URL {newurl!r}", headers, fp
            )
        if _GATE_SEGMENT.search(parsed.path or ""):
            raise AccessDenied(denial_message(newurl, "a redirect to a human gate"), status=code)
        if self._on_redirect is not None:
            # Each hop is its own egress: host consent, rate limit and budget apply.
            self._on_redirect(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener(
    *, allow_hosts: Iterable[str] = (), on_redirect: Callable[[str], object] | None = None
) -> urllib.request.OpenerDirector:
    allow = tuple(allow_hosts)
    http_cls, https_cls = _connection_classes(allow)

    class _HTTP(urllib.request.HTTPHandler):
        def http_open(self, req):  # noqa: ANN001, ANN201
            return self.do_open(http_cls, req)

    class _HTTPS(urllib.request.HTTPSHandler):
        def https_open(self, req):  # noqa: ANN001, ANN201
            return self.do_open(https_cls, req, context=self._context)

    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}),  # no ambient proxies
        urllib.request.UnknownHandler(),
        _HTTP(),
        _HTTPS(),
        urllib.request.HTTPDefaultErrorHandler(),
        _RedirectGuard(on_redirect),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def looks_like_challenge(body: bytes, headers: object = None) -> bool:
    """Cloudflare's ``cf-mitigated`` header, or a challenge mark in a small HTML page."""
    get = getattr(headers, "get", None)
    if callable(get) and str(get("cf-mitigated") or "").lower() == "challenge":
        return True
    if len(body) > _CHALLENGE_SCAN_LIMIT:
        return False
    text = body.decode("utf-8", errors="replace").lower()
    return any(mark in text for mark in (*_CHALLENGE_PAGES, *_CAPTCHAS))


def read_capped(response, max_bytes: int) -> tuple[bytes, bool]:  # noqa: ANN001
    """Read at most ``max_bytes`` from a response; returns ``(body, truncated)``."""
    chunks: list[bytes] = []
    total = 0
    while total <= max_bytes:
        chunk = response.read(min(65536, max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks), False
        chunks.append(chunk)
        total += len(chunk)
    body = b"".join(chunks)
    return body[:max_bytes], True


def retry_after_seconds(headers: object) -> float | None:
    get = getattr(headers, "get", None)
    raw = get("Retry-After") if callable(get) else None
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None
    return value if 0 <= value <= MAX_RETRY_AFTER else None


def sleep(seconds: float) -> None:  # indirection so tests can skip the wait
    time.sleep(seconds)
