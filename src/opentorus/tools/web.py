"""General web access: fetch a URL and run a keyword web search.

The literature tools (``lit_search``) cover scholarly databases, but the agent
also needs to read an arbitrary page the user points at (e.g. a Wikipedia entry
with a conjecture's exact statement) and to discover pages by keyword. These two
helpers provide that, using only the standard library and the shared, polite
HTTP helpers in :mod:`opentorus.research.sources.base`.

Both tools that wrap these helpers carry ``permission = "external"`` so every
call is gated by the agent's egress policy (blocked in review mode, confirmed in
ask mode). Output is converted to plain text and length-capped so a single fetch
can never flood the context window or be used for bulk harvesting.
"""

from __future__ import annotations

import html
import re
import urllib.parse

from opentorus.research.sources.base import SourceError, http_get_text

DEFAULT_MAX_CHARS = 8000

# DuckDuckGo's keyless HTML endpoint returns server-rendered results we can parse
# with the standard library — no API key and no extra dependency.
_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_BLANKS_RE = re.compile(r"[ \t\f\v]+")
_NEWLINES_RE = re.compile(r"\n\s*\n\s*\n+")
# Block-level tags whose boundaries should become line breaks in plain text.
_BLOCK_RE = re.compile(
    r"</?(p|div|section|article|header|footer|li|tr|h[1-6]|br|ul|ol|table|blockquote|pre)\b[^>]*>",
    re.IGNORECASE,
)
# DuckDuckGo result links: <a class="result__a" href="...">title</a>
_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def html_to_text(raw: str) -> tuple[str, str]:
    """Return ``(title, text)`` extracted from an HTML document.

    Scripts/styles are dropped, block tags become line breaks, remaining tags are
    stripped, and entities are unescaped. Non-HTML input is returned mostly as-is.
    """
    title_match = _TITLE_RE.search(raw)
    title = _clean_inline(title_match.group(1)) if title_match else ""

    body = _SCRIPT_STYLE_RE.sub(" ", raw)
    body = _BLOCK_RE.sub("\n", body)
    body = _TAG_RE.sub("", body)
    body = html.unescape(body)
    body = _BLANKS_RE.sub(" ", body)
    body = "\n".join(line.strip() for line in body.splitlines())
    body = _NEWLINES_RE.sub("\n\n", body).strip()
    return title, body


def _clean_inline(raw: str) -> str:
    return html.unescape(_TAG_RE.sub("", raw)).strip()


def fetch_url(url: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, str, bool]:
    """Fetch ``url`` and return ``(title, text, truncated)``.

    Only ``http``/``https`` URLs are allowed. HTML is converted to readable text;
    the result is capped at ``max_chars`` characters. Raises :class:`SourceError`
    on an unreachable host or non-success status.
    """
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SourceError(f"Refusing to fetch non-http(s) URL: {url!r}")

    raw = http_get_text(url)
    title, text = html_to_text(raw)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rstrip() + "\n…[truncated]"
    return title, text, truncated


def web_search(query: str, *, limit: int = 5) -> list[tuple[str, str]]:
    """Run a keyless web search and return up to ``limit`` ``(title, url)`` pairs."""
    url = f"{_SEARCH_ENDPOINT}?{urllib.parse.urlencode({'q': query})}"
    raw = http_get_text(url)
    results: list[tuple[str, str]] = []
    for href, label in _RESULT_RE.findall(raw):
        title = _clean_inline(label)
        target = _resolve_ddg_href(href)
        if title and target:
            results.append((title, target))
        if len(results) >= limit:
            break
    return results


def _resolve_ddg_href(href: str) -> str:
    """Unwrap DuckDuckGo's redirect links (``/l/?uddg=<encoded-url>``)."""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.path.endswith("/l/") or "uddg" in parsed.query:
        params = urllib.parse.parse_qs(parsed.query)
        target = params.get("uddg", [""])[0]
        if target:
            return target
    return href
