"""Tests for gap analysis and hypothesis generation (Milestone 49).

Gaps are detected from a seeded knowledge graph; generated hypotheses carry
evidence links and a verification path; nothing is marked verified.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.claims import list_claims, new_claim
from opentorus.research.knowledge import link_paper_to_claim, propose_hypotheses
from opentorus.research.memory import list_memory
from opentorus.research.papers import acquire_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _paper(ot: Path, doi: str):
    return acquire_paper(
        ot, SourceRecord(source="crossref", title=f"P {doi}", doi=doi), downloader=lambda u: b"%PDF"
    )


def test_propose_hypotheses_for_unsupported_and_contradicted(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    paper = _paper(ot, "10.1/a")
    unsupported = new_claim(ot, "Method scales to billions of rows.")
    contested = new_claim(ot, "Approach is optimal.")
    link_paper_to_claim(ot, paper.id, contested.id, direction="supports", strength="strong")
    link_paper_to_claim(ot, paper.id, contested.id, direction="contradicts", strength="moderate")

    hypotheses = propose_hypotheses(ot)
    texts = [h.text for h in hypotheses]
    assert any(unsupported.id in t for t in texts)
    assert any(contested.id in t for t in texts)


def test_hypotheses_carry_evidence_and_verification(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    paper = _paper(ot, "10.1/b")
    claim = new_claim(ot, "Claim with contradicting evidence.")
    link_paper_to_claim(ot, paper.id, claim.id, direction="contradicts", strength="strong")

    hypotheses = propose_hypotheses(ot)
    target = next(h for h in hypotheses if claim.id in h.text)
    assert "evidence: EVIDENCE-" in target.text
    assert "verification:" in target.text
    assert "Replicate" in target.text  # contradiction -> replication path


def test_unsupported_hypothesis_has_literature_path(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "Totally unsupported assertion.")
    hypotheses = propose_hypotheses(ot)
    target = next(h for h in hypotheses if claim.id in h.text)
    assert "evidence: none yet" in target.text
    assert "Search the literature" in target.text


def test_hypotheses_stored_as_memory_not_claims(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    new_claim(ot, "Unsupported.")
    before = len(list_claims(ot))
    propose_hypotheses(ot)
    assert len(list_memory(ot, "hypotheses")) >= 1
    # No new claims created, and none promoted to verified.
    after = list_claims(ot)
    assert len(after) == before
    assert all(c.status != "verified" for c in after)
