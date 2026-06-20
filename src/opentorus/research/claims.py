"""Research claim tracking with explicit status discipline.

A claim is never silently "true". Each claim carries a status, an
``allowed_usage`` note describing how it may be cited, and lists of support,
dependencies, counterexamples, and limitations. Upgrades toward stronger
statuses (``partially_validated`` and beyond) require explicit confirmation so a
machine can never self-promote a claim to "verified".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import next_id, read_jsonl, rewrite_jsonl
from opentorus.research.epistemics import PROOF_REQUIRED_STATUSES

ClaimStatus = Literal[
    "idea",
    "observation",
    "evidence",
    "hypothesis",
    "partially_validated",
    "human_reviewed",
    "verified",
    "refuted",
    # Math-work rigor ladder (Milestone 52):
    "conjecture",
    "numerical_evidence",
    "proof_sketch",
    "formally_verified",
]

VALID_STATUSES: tuple[ClaimStatus, ...] = (
    "idea",
    "observation",
    "evidence",
    "hypothesis",
    "partially_validated",
    "human_reviewed",
    "verified",
    "refuted",
    "conjecture",
    "numerical_evidence",
    "proof_sketch",
    "formally_verified",
)

# Statuses that may only be reached with explicit user confirmation.
RESTRICTED_STATUSES: frozenset[str] = frozenset(
    {"partially_validated", "human_reviewed", "verified", "formally_verified"}
)

# Statuses that additionally require an accepted formal proof artifact (M51).
# Single-sourced in opentorus.research.epistemics (imported at module top) so the
# global and dossier stacks share one definition of the invariant.

ALLOWED_USAGE: dict[ClaimStatus, str] = {
    "idea": "May be discussed as an idea only.",
    "observation": "May be discussed as an observation, not as a validated result.",
    "evidence": "May support a hypothesis, not a verified conclusion.",
    "hypothesis": "May be stated as a hypothesis, not as verified truth.",
    "partially_validated": "May be used with explicit limitations.",
    "human_reviewed": "May be used as human-reviewed result.",
    "verified": "May be used as verified result.",
    "refuted": "Do not use except as a known false route.",
    "conjecture": "May be stated as a conjecture only — open, unproven.",
    "numerical_evidence": (
        "May cite bounded numerical evidence (state the searched range); not a proof."
    ),
    "proof_sketch": "May present a proof sketch explicitly labelled as not checked.",
    "formally_verified": "May be stated as formally verified (cite the proof artifact).",
}


# Status-accurate language so reports neither over- nor under-claim (M63).
STATUS_LANGUAGE: dict[ClaimStatus, str] = {
    "idea": "an idea",
    "observation": "an observation",
    "evidence": "supported by evidence",
    "hypothesis": "a hypothesis",
    "partially_validated": "partially validated",
    "human_reviewed": "human-reviewed",
    "verified": "verified",
    "refuted": "refuted",
    "conjecture": "a conjecture (open, unproven)",
    "numerical_evidence": "supported by bounded numerical evidence",
    "proof_sketch": "a proof sketch (not machine-checked)",
    "formally_verified": "formally verified",
}


def rigor_phrase(
    status: ClaimStatus,
    *,
    backend: str | None = None,
    domain: str | None = None,
    searched_to: int | None = None,
) -> str:
    """Return status-accurate language for a claim's rigor level.

    Distinguishes a rigorous bound ("rigorous bound on [a,b]") from a formal
    proof ("verified by Z3") from bounded sampling ("evidence up to N").
    """
    if status == "formally_verified" and backend:
        return f"verified by {backend}"
    if status == "numerical_evidence":
        if domain:
            return (
                f"rigorous bound on {domain}"
                if backend == "interval"
                else (f"numerical evidence on {domain}")
            )
        if searched_to is not None:
            return f"evidence up to {searched_to} (bounded; not a proof)"
    return STATUS_LANGUAGE.get(status, status)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Claim(BaseModel):
    id: str
    statement: str
    # Problem dossier this claim was created under (attribution). None for legacy
    # records or claims created outside any active problem.
    problem_id: str | None = None
    status: ClaimStatus = "idea"
    support: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    counterexamples: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    allowed_usage: str = ALLOWED_USAGE["idea"]
    notes: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


ConfirmCallback = Callable[[ClaimStatus, ClaimStatus], bool]


def claims_path(ot_dir: Path) -> Path:
    return ot_dir / "memory" / "claims.jsonl"


def list_claims(ot_dir: Path, *, problem_id: str | None = None) -> list[Claim]:
    claims = read_jsonl(claims_path(ot_dir), Claim)
    if problem_id is not None:
        return [c for c in claims if c.problem_id == problem_id]
    return claims


def get_claim(ot_dir: Path, claim_id: str) -> Claim | None:
    for claim in list_claims(ot_dir):
        if claim.id == claim_id:
            return claim
    return None


def new_claim(ot_dir: Path, statement: str, *, problem_id: str | None = None) -> Claim:
    path = claims_path(ot_dir)
    existing = read_jsonl(path, Claim)
    claim = Claim(
        id=next_id("CLAIM", (c.id for c in existing)),
        statement=statement,
        problem_id=problem_id,
        status="idea",
        allowed_usage=ALLOWED_USAGE["idea"],
    )
    existing.append(claim)
    rewrite_jsonl(path, existing)
    return claim


def update_claim(
    ot_dir: Path,
    claim_id: str,
    *,
    status: ClaimStatus | None = None,
    add_support: str | None = None,
    confirm: ConfirmCallback | None = None,
) -> Claim:
    """Update a claim's status and/or support, enforcing status discipline."""
    if status is not None and status not in VALID_STATUSES:
        raise OpenTorusError(f"Invalid claim status '{status}'. Valid: {', '.join(VALID_STATUSES)}")

    claims = list_claims(ot_dir)
    target = next((c for c in claims if c.id == claim_id), None)
    if target is None:
        raise OpenTorusError(f"No claim with id '{claim_id}'.")

    if status is not None and status != target.status:
        if status in PROOF_REQUIRED_STATUSES:
            from opentorus.research.epistemics import assert_proof_required
            from opentorus.research.verifiers.proofs import accepted_proof_for_claim

            assert_proof_required(
                status, has_proof=accepted_proof_for_claim(ot_dir, claim_id) is not None
            )
        if status in RESTRICTED_STATUSES:
            approved = confirm(target.status, status) if confirm is not None else False
            if not approved:
                raise OpenTorusError(
                    f"Upgrading a claim to '{status}' requires explicit confirmation."
                )
        target.status = status
        target.allowed_usage = ALLOWED_USAGE[status]

    if add_support and add_support not in target.support:
        target.support.append(add_support)

    target.updated_at = _utcnow()
    rewrite_jsonl(claims_path(ot_dir), claims)
    return target
