"""Tests for the cross-workspace knowledge base (Milestone 73).

Fully offline. The KB directory is redirected to a tmp path so the user's real
``~/.opentorus/kb`` is never touched.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opentorus.research.kb import (
    list_kb_entries,
    mark_checked,
    promote_citations,
    promote_paper,
    query_kb,
    stale_entries,
)
from opentorus.research.knowledge import link_citation
from opentorus.research.papers import Paper, _save_meta


def _ot(tmp_path, name=".opentorus"):  # noqa: ANN001
    ot = tmp_path / name
    ot.mkdir()
    return ot


def _register_paper(ot, paper_id, **kwargs):  # noqa: ANN001
    source = kwargs.pop("source", "manual")
    paper = Paper(id=paper_id, source=source, source_type="manual", **kwargs)
    _save_meta(ot, paper)
    return paper


@pytest.fixture(autouse=True)
def _kb_in_tmp(tmp_path, monkeypatch):  # noqa: ANN001, ANN202
    monkeypatch.setenv("OPENTORUS_KB_DIR", str(tmp_path / "kb"))


def test_promote_paper_dedups_by_doi(tmp_path) -> None:  # noqa: ANN001
    ws1 = _ot(tmp_path, "ws1")
    ws2 = _ot(tmp_path, "ws2")
    _register_paper(ws1, "PAPER-0001", title="Tori", doi="10.1/x", abstract="About tori.")
    _register_paper(ws2, "PAPER-0001", title="Tori (copy)", doi="10.1/X")

    entry1, created1 = promote_paper(ws1, "PAPER-0001")
    assert created1 is True
    entry2, created2 = promote_paper(ws2, "PAPER-0001")
    assert created2 is False  # same DOI (case-insensitive) -> dedup
    assert entry2.id == entry1.id
    assert len([e for e in list_kb_entries() if e.kind == "paper"]) == 1
    # Provenance of the first promotion is preserved.
    assert entry1.origin_workspace == str(ws1)
    assert entry1.origin_id == "PAPER-0001"


def test_promote_paper_dedups_by_content_hash(tmp_path) -> None:  # noqa: ANN001
    ws = _ot(tmp_path, "ws")
    _register_paper(ws, "PAPER-0001", title="A", sha256="deadbeef")
    _register_paper(ws, "PAPER-0002", title="A-dup", sha256="DEADBEEF")
    e1, c1 = promote_paper(ws, "PAPER-0001")
    e2, c2 = promote_paper(ws, "PAPER-0002")
    assert c1 is True and c2 is False
    assert e2.id == e1.id


def test_cross_workspace_query_returns_kb_hits(tmp_path) -> None:  # noqa: ANN001
    ws1 = _ot(tmp_path, "ws1")
    _register_paper(
        ws1,
        "PAPER-0001",
        title="Spectral gaps of operators",
        doi="10.2/a",
        abstract="bounds on the spectral gap",
    )
    promote_paper(ws1, "PAPER-0001")

    # A second, unrelated workspace can query the shared KB.
    hits = query_kb("spectral gap")
    assert hits
    assert hits[0][0].doi == "10.2/a"
    assert query_kb("completely unrelated topic xyzzy") == []


def test_stale_entry_flagged_for_recheck(tmp_path) -> None:  # noqa: ANN001
    ws = _ot(tmp_path, "ws")
    _register_paper(ws, "PAPER-0001", title="Old result", doi="10.3/old")
    entry, _ = promote_paper(ws, "PAPER-0001")

    # Nothing is stale right now.
    assert stale_entries(staleness_days=90) == []
    # Far in the future, the entry is due for re-check.
    future = datetime(2999, 1, 1, tzinfo=UTC)
    stale = stale_entries(staleness_days=90, now=future)
    assert [e.id for e in stale] == [entry.id]

    # Re-checking resets the clock (without changing status/content).
    mark_checked(entry.id, now=future)
    assert stale_entries(staleness_days=90, now=future) == []


def test_promote_citations_between_kb_papers(tmp_path) -> None:  # noqa: ANN001
    ws = _ot(tmp_path, "ws")
    _register_paper(ws, "PAPER-0001", title="Citing", doi="10.4/citing")
    _register_paper(ws, "PAPER-0002", title="Cited", doi="10.4/cited")
    promote_paper(ws, "PAPER-0001")
    promote_paper(ws, "PAPER-0002")
    link_citation(ws, "PAPER-0001", "PAPER-0002")

    created = promote_citations(ws)
    assert len(created) == 1
    assert created[0].relation == "cites"
    # Idempotent: re-promoting adds nothing.
    assert promote_citations(ws) == []
