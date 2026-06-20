"""Tests for paper citation validation and literature-phase guards."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.literature_gate import literature_tool_gate
from opentorus.research.paper_citations import (
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
    assert not any("2.1" in w for w in warnings)


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
