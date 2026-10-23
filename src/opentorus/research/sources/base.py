"""Common types and HTTP helpers for literature sources.

A :class:`SourceRecord` is the normalized result every connector returns. The
HTTP helpers use only the standard library (no extra dependency) and raise a
clear :class:`SourceError` on failure so one broken source never crashes a
search.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, Field

USER_AGENT = "OpenTorus/0.2 (+https://github.com/opentorus/opentorus)"
DEFAULT_TIMEOUT = 30


class SourceError(RuntimeError):
    """Raised when a literature source is unreachable or returns an error.

    ``status`` carries the HTTP status code when the failure was an HTTP error
    (``None`` for connection/DNS/timeout failures). Callers use it to tell benign,
    expected conditions — a missing/invalid API key (401/403), no matching results
    (404), or a rate limit (429) — apart from genuine errors, so they can stay
    quiet by default instead of emitting noisy warnings.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class SourceRecord(BaseModel):
    """A normalized bibliographic record from any source."""

    source: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    is_open_access: bool | None = None
    pdf_url: str | None = None
    url: str | None = None
    external_id: str | None = None
    citation_count: int | None = None


class LiteratureSource(ABC):
    """Uniform interface implemented by every connector."""

    name: str = "base"
    requires_key: bool = False
    host: str = ""
    # Field hints (e.g. "cs", "math", "bio", "physics") let the research loop pick
    # relevant sources per topic; empty means general-purpose.
    fields: tuple[str, ...] = ()

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        raise NotImplementedError

    def lookup_doi(self, doi: str) -> SourceRecord | None:  # pragma: no cover - optional
        """Resolve a single DOI to a record, if the source supports it."""
        return None


_BOOLEAN_OPS = re.compile(r"\b(?:AND|OR|NOT|ANDNOT)\b")


def normalize_search_query(query: str) -> str:
    """Reduce a free-form query to clean positive keywords every connector can handle.

    Models write Google-style queries — quoted phrases, ``-exclusions``, ``author:`` /
    ``OR`` operators. The connector APIs do not honor these, and arXiv's ``all:`` field
    actively misreads them: a leading ``-`` is parsed as a token to *include*, so an
    exclusion backfires — the query broadens to millions of hits and surfaces exactly the
    off-topic papers the model tried to remove. That produced an observed ``opentorus
    prove`` livelock where the model kept appending ``-microwave -qcd …`` and the same
    junk kept ranking higher. Dropping the operators and keeping the positive terms gives
    a focused, predictable query (and ``ANDNOT`` / quoted-phrase translation was found
    unreliable on arXiv, so we do not attempt it). Idempotent on already-clean queries.
    """
    q = query
    q = re.sub(r'-"[^"]*"', " ", q)  # drop negated quoted phrases: -"polar decomposition"
    q = re.sub(r"(?<!\S)-\s*\S+", " ", q)  # drop negated bare terms: -microwave, - laa
    q = _BOOLEAN_OPS.sub(" ", q)  # drop standalone boolean operators (terms implicitly AND)
    q = re.sub(r"\b\w+:", " ", q)  # strip field qualifiers (author:, cat:, ti:), keep value
    q = q.replace('"', " ")  # phrase quoting is unreliable across connectors
    # Keep only tokens with an alphanumeric (drops stray punctuation like a lone '-').
    return " ".join(tok for tok in q.split() if re.search(r"\w", tok))


def build_url(base: str, params: dict[str, object]) -> str:
    clean = {k: str(v) for k, v in params.items() if v is not None and v != ""}
    return f"{base}?{urllib.parse.urlencode(clean)}" if clean else base


def _timeout_message(url: str, timeout: int) -> str:
    """Message for a read timeout.

    ``urlopen`` raises a bare :class:`TimeoutError` on a read timeout. It is an
    ``OSError`` but *not* a ``urllib.error.URLError``, so a handler that catches only
    ``URLError`` lets it escape and end a long run with a raw traceback. Every literature
    fetch goes through here, so that failure mode has to be a clean, resumable error.
    """
    return (
        f"Timed out after {timeout}s waiting for {url}. This is a transient "
        "server/network hiccup, not a permanent failure — recorded artifacts are "
        "preserved, so re-running resumes from them."
    )


class AccessDeniedError(SourceError):
    """The site refused (captcha, challenge, human gate, rate limit). Never work around it."""


class BlockedDestinationError(SourceError):
    """The URL (or a redirect hop) resolves to a loopback/private/internal address."""


# Bounds on one response body. Text APIs answer in kilobytes; PDFs can be large.
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_BINARY_BYTES = 256 * 1024 * 1024


def _open_url(
    request: urllib.request.Request,
    timeout: float,
    *,
    allow_hosts: tuple[str, ...] = (),
    on_redirect: Callable[[str], object] | None = None,
):  # noqa: ANN202
    """Open ``request`` through the guarded opener (see :mod:`opentorus.tools.netguard`)."""
    from opentorus.tools.netguard import build_opener

    opener = build_opener(allow_hosts=allow_hosts, on_redirect=on_redirect)
    return opener.open(request, timeout=timeout)


def http_fetch(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    max_bytes: int = MAX_TEXT_BYTES,
    truncate: bool = False,
    allow_hosts: Iterable[str] = (),
    on_redirect: Callable[[str], object] | None = None,
    detect_challenge: bool = False,
) -> tuple[bytes, bool]:
    """GET ``url`` through the guard; returns ``(body, truncated)``.

    Internal destinations are refused on every hop, the body is streamed up to
    ``max_bytes`` (beyond it: truncated when ``truncate``, else an error), and a
    site's refusal raises :class:`AccessDeniedError`. A 429/503 carrying a short
    ``Retry-After`` is waited out exactly once.
    """
    from opentorus.tools import netguard

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    allow = tuple(allow_hosts)
    waited = False
    while True:
        try:
            with _open_url(request, timeout, allow_hosts=allow, on_redirect=on_redirect) as resp:
                body, cut = netguard.read_capped(resp, max_bytes)
                if detect_challenge and netguard.looks_like_challenge(body, resp.headers):
                    raise AccessDeniedError(
                        netguard.denial_message(url, "a captcha / challenge page"), status=200
                    )
                if cut and not truncate:
                    raise SourceError(f"Response from {url} exceeds {max_bytes} bytes; refused.")
                return body, cut
        except urllib.error.HTTPError as exc:
            try:
                detail_bytes, _ = netguard.read_capped(exc, _ERROR_BODY_BYTES)
            except (OSError, ValueError):
                detail_bytes = b""
            if exc.code in (403, 429, 503) and netguard.looks_like_challenge(
                detail_bytes, exc.headers
            ):
                raise AccessDeniedError(
                    netguard.denial_message(url, f"a captcha / challenge (HTTP {exc.code})"),
                    status=exc.code,
                ) from exc
            if exc.code in (429, 503) and not waited:
                delay = netguard.retry_after_seconds(exc.headers)
                if delay is not None:
                    waited = True
                    netguard.sleep(delay)
                    continue
            if exc.code == 429:
                raise AccessDeniedError(
                    netguard.denial_message(url, "rate limited (HTTP 429)"), status=429
                ) from exc
            detail = detail_bytes.decode("utf-8", errors="replace")[:200]
            raise SourceError(
                f"HTTP {exc.code} from {url}: {detail or exc.reason}", status=exc.code
            ) from exc
        except netguard.AccessDenied as exc:
            raise AccessDeniedError(str(exc), status=exc.status) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, netguard.BlockedAddress):
                raise BlockedDestinationError(str(exc.reason)) from exc
            if isinstance(exc.reason, TimeoutError):
                raise SourceError(_timeout_message(url, timeout)) from exc
            raise SourceError(f"Could not reach {url}: {exc}") from exc
        except netguard.BlockedAddress as exc:
            raise BlockedDestinationError(str(exc)) from exc
        except TimeoutError as exc:
            raise SourceError(_timeout_message(url, timeout)) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise SourceError(f"Could not reach {url}: {exc}") from exc


_ERROR_BODY_BYTES = 64 * 1024


def http_get_text(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    **guard: Any,
) -> str:
    body, _ = http_fetch(url, headers, timeout, **guard)
    return body.decode("utf-8", errors="replace")


def http_get_bytes(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    **guard: Any,
) -> bytes:
    guard.setdefault("max_bytes", MAX_BINARY_BYTES)
    body, _ = http_fetch(url, headers, timeout, **guard)
    return body


def http_get_json(
    url: str, headers: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT
) -> dict:
    text = http_get_text(url, headers=headers, timeout=timeout)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceError(f"Invalid JSON from {url}: {exc}") from exc
    if not isinstance(data, dict):
        raise SourceError(f"Unexpected non-object JSON from {url}.")
    return data
