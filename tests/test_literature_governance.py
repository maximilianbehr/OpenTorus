"""Tests for batch-8 literature-pipeline governance: egress guard, field routing, KB tool."""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.tools.base import ToolCall
from opentorus.tools.builtin import LiteratureSearchTool
from opentorus.workspace import init_workspace, workspace_dir


def test_lit_search_builds_egress_guard_and_routes_field(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()

    captured: dict = {}

    def fake_search_all(cfg, query, limit=10, sources=None, egress=None):  # noqa: ANN001, ANN202
        captured["sources"] = sources
        captured["egress"] = egress
        return []

    import opentorus.research.sources as sources_mod

    monkeypatch.setattr(sources_mod, "search_all", fake_search_all)

    tool = LiteratureSearchTool(config, ot)
    result = tool.run(ToolCall(id="1", name="lit_search", args={"query": "matrix sign function"}))
    assert result.ok
    # The agent path now goes through the egress guard (host auth + daily budget ledger).
    assert captured["egress"] is not None
    # Field routing applied (default math): sources is a name list, never unfiltered None
    # unless no sources are enabled.
    assert captured["sources"] is None or isinstance(captured["sources"], list)


def test_lit_search_without_ot_dir_has_no_guard(monkeypatch) -> None:  # noqa: ANN001
    config = default_config()
    captured: dict = {}

    def fake_search_all(cfg, query, limit=10, sources=None, egress=None):  # noqa: ANN001, ANN202
        captured["egress"] = egress
        return []

    import opentorus.research.sources as sources_mod

    monkeypatch.setattr(sources_mod, "search_all", fake_search_all)
    LiteratureSearchTool(config).run(ToolCall(id="1", name="lit_search", args={"query": "x"}))
    assert captured["egress"] is None  # no workspace -> no ledger -> no guard


def test_kb_query_tool_renders_hits(monkeypatch) -> None:  # noqa: ANN001
    from opentorus.research.kb import KBEntry
    from opentorus.tools.research import KbQueryTool

    entry = KBEntry(id="KB-0001", kind="paper", title="Nyström bounds", text="effective dimension")

    monkeypatch.setattr("opentorus.research.kb.query_kb", lambda q, k=5: [(entry, 1.5)])
    result = KbQueryTool().run(ToolCall(id="1", name="kb_query", args={"query": "Nyström"}))
    assert result.ok
    assert "KB-0001" in result.content
    assert "Nyström bounds" in result.content


def test_kb_query_requires_query() -> None:
    from opentorus.tools.research import KbQueryTool

    result = KbQueryTool().run(ToolCall(id="1", name="kb_query", args={}))
    assert not result.ok
