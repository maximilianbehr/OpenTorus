"""Tests for the critic agent & review protocol (Milestone 58).

Claim reviews yield honesty findings when overclaimed; findings persist as REVIEW-*.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.review import get_review, list_reviews, review_target
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _claim(ot: Path, statement: str):
    from opentorus.research.claims import new_claim

    return new_claim(ot, statement)


def test_overclaimed_claim_yields_blocking_finding(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "We have proven the main theorem. QED.")
    review = review_target(ot, claim.id)
    assert review.verdict == "block"
    assert any(f.category == "honesty" and f.severity == "blocking" for f in review.findings)


def test_review_is_persisted(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "A bounded numerical observation.")
    review = review_target(ot, claim.id)
    assert get_review(ot, review.id) is not None
    assert list_reviews(ot, claim.id)
    assert (ot / "reviews" / f"{review.id}.md").is_file()


def test_review_unknown_target_fails(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    try:
        review_target(ot, "CLAIM-9999")
        raise AssertionError("expected failure for unknown target")
    except Exception as exc:  # noqa: BLE001
        assert "No claim" in str(exc)
