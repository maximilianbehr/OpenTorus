"""Tests for rigor-ladder integration (Milestone 63).

A claim backed by an unsat SMT proof can reach formally_verified (with explicit
confirmation); a claim with only sampled evidence cannot; status-accurate
language passes the honesty linter while overclaims are flagged. Offline.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.research.claims import new_claim, rigor_phrase, update_claim
from opentorus.research.honesty import lint_text
from opentorus.research.math_experiments import counterexample_search, record_search_evidence
from opentorus.research.verifiers import submit_proof
from opentorus.research.verifiers.base import VerificationResult
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


class UnsatSMT:
    name = "smt"

    def is_available(self) -> bool:
        return True

    def version(self) -> str | None:
        return "stub-z3"

    def verify(self, source: str) -> VerificationResult:
        return VerificationResult(
            backend="smt", backend_version="stub-z3", accepted=True, outcome="unsat", output="unsat"
        )


def test_unsat_proof_enables_formally_verified(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "x + 0 = x for all integers.")
    submit_proof(ot, default_config(), "smt", "(check-sat)", claim_id=claim.id, verifier=UnsatSMT())
    updated = update_claim(ot, claim.id, status="formally_verified", confirm=lambda a, b: True)
    assert updated.status == "formally_verified"


def test_sampled_evidence_cannot_reach_formally_verified(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "P(n) holds for all n.")
    result = counterexample_search(lambda n: True, 1, 1000, description="P(n)")
    record_search_evidence(ot, claim.id, result)
    try:
        update_claim(ot, claim.id, status="formally_verified", confirm=lambda a, b: True)
        raise AssertionError("sampled evidence must not reach formally_verified")
    except Exception as exc:  # noqa: BLE001
        assert "accepted formal proof" in str(exc)


def test_language_checks_distinguish_rigor_levels() -> None:
    # Proof-tier: "verified by Z3" needs a formal proof artifact.
    assert lint_text("We verified by Z3 that x > 0.")
    assert lint_text("We verified by Z3 that x > 0.", has_formal_proof=True) == []
    # Bound-tier: "rigorous bound" needs a validated-numerics enclosure.
    assert lint_text("This is a rigorous bound on [0, 1].")
    assert lint_text("This is a rigorous bound on [0, 1].", has_rigorous_bound=True) == []
    # Honest, status-accurate language passes.
    assert lint_text("We have numerical evidence up to N = 10000.") == []


def test_rigor_phrase_is_status_accurate() -> None:
    assert rigor_phrase("formally_verified", backend="Z3") == "verified by Z3"
    assert "evidence up to 100" in rigor_phrase("numerical_evidence", searched_to=100)
    assert rigor_phrase("numerical_evidence", backend="interval", domain="[0, 1]") == (
        "rigorous bound on [0, 1]"
    )
    assert rigor_phrase("conjecture") == "a conjecture (open, unproven)"
