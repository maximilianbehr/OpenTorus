"""Tests for citation & proof attacks (Milestone 59)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.review import challenge_claim_numerically, review_target
from opentorus.research.evidence import list_evidence
from opentorus.research.graph import related
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _claim(ot: Path, statement: str):
    from opentorus.research.claims import new_claim

    return new_claim(ot, statement)


def test_planted_counterexample_is_challenged_and_recorded(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "P(n) holds for all n.")
    review, result = challenge_claim_numerically(
        ot, claim.id, lambda n: n != 7, 1, 100, description="n != 7"
    )
    assert result.found is True
    assert review.verdict == "block"
    evidence = list_evidence(ot, claim.id)
    assert any(e.direction == "contradicts" for e in evidence)
    edges = related(ot, review.id)
    assert any(e.relation == "contradicts" and e.target_id == claim.id for e in edges)


def test_clean_search_no_blocking_finding(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "Q(n) holds.")
    review, result = challenge_claim_numerically(ot, claim.id, lambda n: True, 1, 50)
    assert result.found is False
    assert review.verdict == "pass"
    assert any(e.direction == "supports" for e in list_evidence(ot, claim.id))


def test_qed_without_proof_is_blocking(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "We have proven the main theorem. QED.")
    review = review_target(ot, claim.id)
    assert review.verdict == "block"
    assert any(f.category == "honesty" for f in review.findings)
