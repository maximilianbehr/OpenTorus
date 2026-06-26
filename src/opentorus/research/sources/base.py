"""Common types and HTTP helpers for literature sources.

A :class:`SourceRecord` is the normalized result every connector returns. The
HTTP helpers use only the standard library (no extra dependency) and raise a
clear :class:`SourceError` on failure so one broken source never crashes a
search.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

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


def http_get_text(
    url: str, headers: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT
) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise SourceError(
            f"HTTP {exc.code} from {url}: {detail or exc.reason}", status=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        raise SourceError(f"Could not reach {url}: {exc}") from exc


def http_get_bytes(
    url: str, headers: dict[str, str] | None = None, timeout: int = DEFAULT_TIMEOUT
) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise SourceError(f"HTTP {exc.code} from {url}: {exc.reason}", status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise SourceError(f"Could not reach {url}: {exc}") from exc


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
