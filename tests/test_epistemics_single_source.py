"""D-step-2: the shared epistemic invariant has a single source of truth.

Both the global research stack and the dossier stack must reference the same
definitions in ``opentorus.research.epistemics`` so the "evidence is not truth"
invariant can never drift between them.
"""

from __future__ import annotations

from opentorus.research import epistemics
from opentorus.research.claims import PROOF_REQUIRED_STATUSES
from opentorus.research.dossier import validation


def test_proof_required_is_single_sourced() -> None:
    assert PROOF_REQUIRED_STATUSES is epistemics.PROOF_REQUIRED_STATUSES
    assert "formally_verified" in PROOF_REQUIRED_STATUSES


def test_verification_evidence_is_single_sourced() -> None:
    assert validation.VERIFICATION_EVIDENCE is epistemics.VERIFICATION_EVIDENCE
    assert validation.VERIFIED_STATUSES is epistemics.VERIFIED_STATUSES


def test_canonical_values() -> None:
    assert epistemics.VERIFICATION_EVIDENCE == frozenset({"FORMAL_PROOF", "VALIDATED_NUMERICAL"})
    assert epistemics.VERIFIED_STATUSES == frozenset({"verified", "formally_verified"})
    assert epistemics.requires_proof("formally_verified") is True
    assert epistemics.requires_proof("verified") is False
    assert epistemics.is_verification_evidence("FORMAL_PROOF") is True
    assert epistemics.is_verification_evidence("EXPERIMENT") is False


def test_dossier_evidence_can_verify_uses_shared_set() -> None:
    # The dossier helper and the shared predicate agree on every evidence kind.
    for kind in ("EXPERIMENT", "COMPUTATION", "FORMAL_PROOF", "VALIDATED_NUMERICAL", "PAPER"):
        assert validation.evidence_can_verify(kind) == epistemics.is_verification_evidence(kind)
