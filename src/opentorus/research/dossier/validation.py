"""Epistemic validation rules for dossier claims and evidence.

These functions are the teeth behind *evidence is not truth*:

* Numerical experiments and proof sketches may **support** a claim but never
  **verify** it.
* Only a verification-grade artifact may move a claim to ``verified`` /
  ``formally_verified``: an accepted formal proof, or a *rigorous* validated-
  numerical certificate (an interval-arithmetic enclosure produced by the
  verifier — ordinary floating-point experiments never qualify).
* A counterexample *candidate* may not be created as *verified* without a
  verification artifact.
* ``THEOREM`` and ``REFERENCE_FACT`` claims may not be asserted without a
  source artifact (a paper / theorem reference or a verified local artifact).

The functions are pure and take explicit booleans so they are trivially
testable; the claims layer computes those booleans from the dossier.
"""

from __future__ import annotations

from opentorus.errors import OpenTorusError
from opentorus.research.dossier.models import (
    ClaimStatus,
    ClaimType,
    EvidenceType,
)
from opentorus.research.epistemics import (
    VERIFICATION_EVIDENCE,
    VERIFIED_STATUSES,
)

# Evidence kinds that, on their own, can never raise a claim to verified status.
# Experiments and sketches are *support*, full stop.
SUPPORT_ONLY_EVIDENCE: frozenset[str] = frozenset(
    {"EXPERIMENT", "COMPUTATION", "PROOF_SKETCH", "PAPER", "REFERENCE", "MANUAL_NOTE"}
)
# VERIFICATION_EVIDENCE and VERIFIED_STATUSES are the cross-cutting invariant —
# imported from opentorus.research.epistemics so the global and dossier stacks
# can never disagree about what counts as verification-grade.

# Claim types that assert a *settled* result and therefore need backing to exist.
VERIFIED_CLAIM_TYPES: frozenset[str] = frozenset(
    {"THEOREM", "COUNTEREXAMPLE_VERIFIED", "FORMAL_PROOF_VERIFIED"}
)
# Claim types that must cite a source (reference or verification) on creation.
SOURCE_REQUIRED_TYPES: frozenset[str] = frozenset({"THEOREM", "REFERENCE_FACT"})


def evidence_can_verify(evidence_type: EvidenceType) -> bool:
    """Return whether this evidence kind is verification-grade.

    Numerical/experimental/sketch/paper evidence is always support-only.
    """
    return evidence_type in VERIFICATION_EVIDENCE


def default_status_for_type(claim_type: ClaimType) -> ClaimStatus:
    if claim_type == "FORMAL_PROOF_VERIFIED":
        return "formally_verified"
    if claim_type == "COUNTEREXAMPLE_VERIFIED":
        return "verified"
    return "unverified"


def assert_can_create_claim(
    claim_type: ClaimType,
    *,
    has_verification_artifact: bool,
    has_source_artifact: bool,
) -> None:
    """Reject claims asserting a settled result without the artifacts to back it."""
    if (
        claim_type in {"COUNTEREXAMPLE_VERIFIED", "FORMAL_PROOF_VERIFIED"}
        and not has_verification_artifact
    ):
        raise OpenTorusError(
            f"Cannot create a '{claim_type}' claim without a verification artifact "
            "(an accepted formal proof or explicit verification record). "
            "Use COUNTEREXAMPLE_CANDIDATE or LEMMA_ATTEMPT until verified."
        )
    if claim_type == "THEOREM" and not (has_source_artifact or has_verification_artifact):
        raise OpenTorusError(
            "A THEOREM claim must cite a source artifact (paper/theorem reference) "
            "or a verified local proof artifact. Otherwise it is a CONJECTURE or "
            "LEMMA_ATTEMPT, not a theorem."
        )
    if claim_type == "REFERENCE_FACT" and not has_source_artifact:
        raise OpenTorusError(
            "A REFERENCE_FACT must link a local source artifact (PAPER-* / theorem "
            "reference). Do not assert 'it is known that …' without a source."
        )


def assert_can_set_status(
    new_status: ClaimStatus,
    *,
    has_verification_artifact: bool,
) -> None:
    """Reject upgrading a claim to verified status without a verification artifact."""
    if new_status in VERIFIED_STATUSES and not has_verification_artifact:
        raise OpenTorusError(
            f"Cannot set claim status to '{new_status}' without a verification "
            "artifact. Numerical experiments and proof sketches only ever 'support' "
            "a claim — they never verify it."
        )
