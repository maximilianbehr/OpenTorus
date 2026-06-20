"""Tests for general web access (fetch_url + web_search) and registry wiring."""

from __future__ import annotations

import pytest

from opentorus.config import Config
from opentorus.research.sources.base import SourceError
from opentorus.tools import web
from opentorus.tools.base import ToolCall
from opentorus.tools.builtin import FetchUrlTool, WebSearchTool, build_default_registry

_WIKI_HTML = """
<html><head><title>Crouzeix's conjecture - Wikipedia</title>
<style>.x{color:red}</style><script>var a=1;</script></head>
<body><p>In <b>matrix analysis</b>, Crouzeix's conjecture states a bound.</p>
<div>The constant is 2.</div></body></html>
"""

_DDG_REDIRECT = (
    "//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FCrouzeix%27s_conjecture"
)
_DDG_HTML = (
    f'<div><a class="result__a" href="{_DDG_REDIRECT}">'
    "Crouzeix's conjecture - Wikipedia</a></div>\n"
    '<div><a class="result__a" href="https://example.org/paper">A direct link</a></div>\n'
)


def test_html_to_text_extracts_title_and_drops_scripts() -> None:
    title, text = web.html_to_text(_WIKI_HTML)
    assert title == "Crouzeix's conjecture - Wikipedia"
    assert "matrix analysis" in text
    assert "The constant is 2." in text
    assert "var a=1" not in text
    assert "color:red" not in text


def test_fetch_url_rejects_non_http() -> None:
    with pytest.raises(SourceError):
        web.fetch_url("file:///etc/passwd")
    with pytest.raises(SourceError):
        web.fetch_url("ftp://example.org/x")


def test_fetch_url_returns_text_and_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "http_get_text", lambda url, **kw: _WIKI_HTML)
    title, text, truncated = web.fetch_url("https://en.wikipedia.org/wiki/x", max_chars=10000)
    assert title.startswith("Crouzeix")
    assert "matrix analysis" in text
    assert truncated is False

    _, short, truncated2 = web.fetch_url("https://en.wikipedia.org/wiki/x", max_chars=20)
    assert truncated2 is True
    assert short.endswith("…[truncated]")


def test_web_search_parses_and_unwraps_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "http_get_text", lambda url, **kw: _DDG_HTML)
    results = web.web_search("crouzeix conjecture", limit=5)
    assert results[0] == (
        "Crouzeix's conjecture - Wikipedia",
        "https://en.wikipedia.org/wiki/Crouzeix's_conjecture",
    )
    assert results[1] == ("A direct link", "https://example.org/paper")


def test_web_search_respects_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "http_get_text", lambda url, **kw: _DDG_HTML)
    assert len(web.web_search("q", limit=1)) == 1


def test_fetch_url_tool_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **kw: object) -> str:
        raise SourceError("unreachable")

    monkeypatch.setattr(web, "http_get_text", boom)
    result = FetchUrlTool().run(ToolCall(name="fetch_url", args={"url": "https://x.test"}))
    assert result.ok is False
    assert "unreachable" in result.content


def test_fetch_url_tool_requires_url() -> None:
    result = FetchUrlTool().run(ToolCall(name="fetch_url", args={}))
    assert result.ok is False


def test_web_search_tool_formats_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "web_search", lambda q, limit=5: [("Title", "https://x.test")])
    result = WebSearchTool().run(ToolCall(name="web_search", args={"query": "x"}))
    assert result.ok is True
    assert "https://x.test" in result.content
    assert result.metadata["count"] == 1


def test_web_tools_are_external_permission() -> None:
    assert FetchUrlTool().permission == "external"
    assert WebSearchTool().permission == "external"


def test_registry_registers_web_tools_by_default(tmp_path) -> None:
    config = Config()
    registry = build_default_registry(tmp_path, tmp_path / ".opentorus", config)
    assert "fetch_url" in registry.names()
    assert "web_search" in registry.names()


def test_registry_omits_web_tools_when_disabled(tmp_path) -> None:
    config = Config()
    config.tools.web.enabled = False
    registry = build_default_registry(tmp_path, tmp_path / ".opentorus", config)
    assert "fetch_url" not in registry.names()
    assert "web_search" not in registry.names()
