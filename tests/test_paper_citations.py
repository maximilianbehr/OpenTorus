"""Tests for paper citation validation and literature-phase guards."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.literature_gate import literature_tool_gate
from opentorus.research.paper_citations import (
    corpus_has_numbered_theorems,
    theorem_in_corpus,
    validate_proof_citations,
)
from opentorus.research.papers import acquire_paper, read_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.workspace import init_workspace


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return tmp_path / ".opentorus"


def test_theorem_in_corpus() -> None:
    text = "We prove Theorem 3.1 on page 5. Lemma 2.4 follows."
    assert theorem_in_corpus(text, "3.1")
    assert theorem_in_corpus(text, "2.4")
    assert not theorem_in_corpus(text, "9.9")


def test_validate_proof_citations_rejects_hallucinated_theorem(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Matrix bounds", arxiv_id="2401.00001")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = [
        "1 Introduction\nWe study matrix functions.\n",
        "2 Results\nTheorem 2.1. The Lanczos error decays exponentially.\n",
    ]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "By Theorem 3.1 in PAPER-0001, tensor networks converge for local Hamiltonians."
    errors, _ = validate_proof_citations(ot, body)
    assert errors
    assert any("3.1" in e for e in errors)


def test_validate_proof_citations_accepts_parsed_theorem(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Matrix bounds", arxiv_id="2401.00002")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = ["2 Results\nTheorem 2.1. The error bound holds on the interval.\n"]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "Apply Theorem 2.1 in PAPER-0001 to bound the sign-function error."
    errors, warnings = validate_proof_citations(ot, body)
    assert not errors
    # A valid parsed theorem citation is accepted, and now gets a non-blocking
    # source-context advisory so a reviewer can confirm the statement matches.
    assert any("source context" in w for w in warnings)


def test_theorem_in_corpus_tolerates_extraction_noise() -> None:
    # PDF extraction often drops the space ("Theorem2.1") or splits the dot ("1 . 3").
    assert theorem_in_corpus("see Theorem2.1 here", "2.1")
    assert theorem_in_corpus("see Theorem 1 . 3 here", "1.3")
    assert corpus_has_numbered_theorems("intro Theorem 4 results")
    assert not corpus_has_numbered_theorems("only prose, no numbered results here")


def test_missing_theorem_warns_when_extraction_has_no_numbering(tmp_path: Path) -> None:
    # The root cause of the random_nla stall: a paper whose extraction captured no
    # numbered theorems must NOT hard-block every citation as "invented" — the
    # grounding cannot verify it either way, so it warns instead.
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Survey", arxiv_id="2401.00003")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = ["Abstract\nThis survey discusses sketching and error estimation in prose only.\n"]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "By Theorem 4.2 of PAPER-0001 the adaptive sketch error is bounded."
    errors, warnings = validate_proof_citations(ot, body)
    assert not errors  # unverifiable, not invented → does not block proof writing
    assert any("cannot verify" in w and "4.2" in w for w in warnings)


def test_missing_theorem_blocks_when_paper_has_other_numbers(tmp_path: Path) -> None:
    # When the paper DOES have numbered results but not the cited one, it is a genuine
    # invention and is still blocked.
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Sparse JL", arxiv_id="2401.00004")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = ["Results\nTheorem 1 holds. Lemma 6 follows. Lemma 9 too.\n"]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "By Theorem 1.3 of PAPER-0001 the projection preserves norms."
    errors, _ = validate_proof_citations(ot, body)
    assert any("1.3" in e for e in errors)


def test_literature_tool_gate_blocks_proof_write() -> None:
    gate = literature_tool_gate()
    msg = gate("proof_write", {"problem_id": "PROBLEM-0001", "title": "x"})
    assert msg is not None
    assert "literature phase" in msg.lower()


def test_literature_tool_gate_requires_paper_id_in_observation() -> None:
    gate = literature_tool_gate(phase_complete=lambda: False)
    blocked = gate("memory_add", {"text": "No paper id here", "kind": "observations"})
    assert blocked is not None
    ok = gate(
        "memory_add",
        {"text": "PAPER-0001 Theorem 2.1: error bound on [-1,1].", "kind": "observations"},
    )
    assert ok is None
