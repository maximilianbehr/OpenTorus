"""Tests for proof-status discipline (Milestone 52).

Status transitions enforce their evidence preconditions; ``formally_verified``
without a proof artifact is refused; and language checks catch overclaiming.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.errors import OpenTorusError
from opentorus.research.claims import (
    PROOF_REQUIRED_STATUSES,
    VALID_STATUSES,
    new_claim,
    update_claim,
)
from opentorus.research.honesty import is_honest, lint_text
from opentorus.research.verifiers import submit_proof
from opentorus.research.verifiers.base import VerificationResult
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


class AcceptingVerifier:
    name = "stub"

    def is_available(self) -> bool:
        return True

    def version(self) -> str | None:
        return "stub-1.0"

    def verify(self, source: str) -> VerificationResult:
        return VerificationResult(
            backend="lean4", backend_version="stub-1.0", accepted=True, output="ok"
        )


def test_math_statuses_present() -> None:
    for status in ("conjecture", "numerical_evidence", "proof_sketch", "formally_verified"):
        assert status in VALID_STATUSES
    assert "formally_verified" in PROOF_REQUIRED_STATUSES


def test_unrestricted_math_status_transition(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "P(n) for all n.")
    updated = update_claim(ot, claim.id, status="conjecture")
    assert updated.status == "conjecture"
    updated = update_claim(ot, claim.id, status="numerical_evidence")
    assert updated.status == "numerical_evidence"
    assert "not a proof" in updated.allowed_usage


def test_formally_verified_refused_without_proof(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "Lemma L.")
    try:
        update_claim(ot, claim.id, status="formally_verified", confirm=lambda a, b: True)
        raise AssertionError("expected refusal without a proof artifact")
    except OpenTorusError as exc:
        assert "accepted formal proof" in str(exc)


def test_formally_verified_requires_confirmation_even_with_proof(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "Lemma L.")
    submit_proof(
        ot, default_config(), "lean4", "theorem L", claim_id=claim.id, verifier=AcceptingVerifier()
    )
    # Proof exists, but no confirmation callback → still refused.
    try:
        update_claim(ot, claim.id, status="formally_verified")
        raise AssertionError("expected refusal without confirmation")
    except OpenTorusError as exc:
        assert "explicit confirmation" in str(exc)


def test_formally_verified_succeeds_with_proof_and_confirmation(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "Lemma L.")
    submit_proof(
        ot, default_config(), "lean4", "theorem L", claim_id=claim.id, verifier=AcceptingVerifier()
    )
    updated = update_claim(ot, claim.id, status="formally_verified", confirm=lambda a, b: True)
    assert updated.status == "formally_verified"


def test_honesty_linter_flags_overclaims() -> None:
    issues = lint_text("We have proven the theorem. QED.")
    phrases = {i.phrase.lower() for i in issues}
    assert any("proven" in p for p in phrases)
    assert any("qed" in p for p in phrases)
    assert not is_honest("This proves the result.")


def test_honesty_linter_allows_with_formal_proof() -> None:
    assert is_honest("We have proven it. QED.", has_formal_proof=True)
    assert lint_text("proven", has_formal_proof=True) == []


def test_honesty_linter_accepts_evidence_language() -> None:
    text = "Bounded numerical evidence up to N=10000; this is a conjecture, not a proof."
    assert is_honest(text)
