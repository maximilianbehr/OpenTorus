"""Tests for the citation/knowledge graph (Milestone 47).

Citation edges link locally-known papers; papers link to claims as evidence with
direction and strength; contradictions are preserved; and the gap query finds
weakly-supported or contradicted claims. No network is used.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.claims import new_claim, update_claim
from opentorus.research.graph import list_edges
from opentorus.research.knowledge import (
    find_gaps,
    ingest_citations,
    link_citation,
    link_paper_to_claim,
    literature_subgraph,
)
from opentorus.research.papers import acquire_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _paper(ot: Path, title: str, doi: str | None = None, arxiv_id: str | None = None):
    record = SourceRecord(source="crossref", title=title, doi=doi, arxiv_id=arxiv_id)
    return acquire_paper(ot, record, downloader=lambda u: b"%PDF")


def test_link_citation_between_local_papers(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    a = _paper(ot, "Citing", doi="10.1/a")
    b = _paper(ot, "Cited", doi="10.1/b")
    edge = link_citation(ot, a.id, "10.1/b")
    assert edge is not None
    assert edge.source_id == a.id and edge.target_id == b.id and edge.relation == "cites"


def test_link_citation_unknown_target_returns_none(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    a = _paper(ot, "Citing", doi="10.1/a")
    assert link_citation(ot, a.id, "10.9/missing") is None


def test_link_citation_is_idempotent(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    a = _paper(ot, "A", doi="10.1/a")
    _paper(ot, "B", doi="10.1/b")
    e1 = link_citation(ot, a.id, "10.1/b")
    e2 = link_citation(ot, a.id, "10.1/b")
    assert e1 is not None and e2 is not None and e1.id == e2.id
    assert len([e for e in list_edges(ot) if e.relation == "cites"]) == 1


def test_ingest_citations_only_links_known(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    a = _paper(ot, "A", doi="10.1/a")
    _paper(ot, "B", arxiv_id="2401.00009")
    edges = ingest_citations(ot, a.id, ["2401.00009", "10.9/missing"])
    assert len(edges) == 1
    assert edges[0].target_id != a.id


def test_paper_to_claim_evidence_and_edge(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    paper = _paper(ot, "Support", doi="10.1/s")
    claim = new_claim(ot, "The method converges.")
    evidence, edge, advisory = link_paper_to_claim(
        ot, paper.id, claim.id, direction="supports", strength="strong", summary="Thm 1"
    )
    assert evidence.source_type == "paper" and evidence.source_id == paper.id
    assert edge.relation == "supports"
    assert advisory is None


def test_contradicting_evidence_is_preserved_and_advised(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    paper = _paper(ot, "Counter", doi="10.1/c")
    claim = new_claim(ot, "X always holds.")
    _, edge, advisory = link_paper_to_claim(
        ot, paper.id, claim.id, direction="contradicts", strength="strong"
    )
    assert edge.relation == "contradicts"
    assert advisory and "contradicts" in advisory


def test_find_gaps_flags_unsupported_and_contradicted(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    # Claim 1: no evidence -> gap (no supporting evidence).
    c1 = new_claim(ot, "Unsupported claim.")
    # Claim 2: strongly supported -> not a gap.
    c2 = new_claim(ot, "Well supported claim.")
    p = _paper(ot, "P", doi="10.1/p")
    link_paper_to_claim(ot, p.id, c2.id, direction="supports", strength="strong")
    # Claim 3: contradicted -> gap even if also supported.
    c3 = new_claim(ot, "Contested claim.")
    link_paper_to_claim(ot, p.id, c3.id, direction="supports", strength="strong")
    link_paper_to_claim(ot, p.id, c3.id, direction="contradicts", strength="moderate")

    gaps = {g.claim_id: g for g in find_gaps(ot)}
    assert c1.id in gaps and "no supporting evidence" in " ".join(gaps[c1.id].reasons)
    assert c2.id not in gaps
    assert c3.id in gaps and gaps[c3.id].contradiction_count == 1


def test_settled_status_not_flagged_when_unsupported(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "Reviewed but unsupported by papers.")
    update_claim(ot, claim.id, status="human_reviewed", confirm=lambda old, new: True)
    gaps = {g.claim_id for g in find_gaps(ot)}
    assert claim.id not in gaps


def test_literature_subgraph_filter(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    a = _paper(ot, "A", doi="10.1/a")
    _paper(ot, "B", doi="10.1/b")
    claim = new_claim(ot, "C")
    link_citation(ot, a.id, "10.1/b")
    link_paper_to_claim(ot, a.id, claim.id)
    sub = literature_subgraph(list_edges(ot))
    assert all(e.source_id.startswith("PAPER") or e.target_id.startswith("PAPER") for e in sub)
    assert len(sub) == 2
