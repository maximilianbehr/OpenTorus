"""Target-scope policy and campaign-level outcome classification.

Implements the general-conjecture scope policy: a dossier's primary target must
be a *general* quantified statement ("for every n", "there exists a universal
constant", "infinitely many …"); fixed instances (a record for one parameter, a
single order or dimension) are internal tools, never primary targets.

This module is a strictly *derived, additive* layer. It never sets or changes a
claim's status — the epistemic invariants enforced in ``dossier.validation``
stay exactly as they are. In particular, the two campaign-resolving labels are
reachable only through verification-grade artifacts:

- ``GENERAL_CONJECTURE_PROVED`` requires the dossier's *designated primary
  claim* (``ProblemDossier.primary_claim_id``) to be ``formally_verified`` —
  a status that itself requires an accepted formal proof artifact — AND a
  general target statement.
- ``GENERAL_CONJECTURE_REFUTED`` requires a ``COUNTEREXAMPLE_VERIFIED`` claim
  (creatable only with an explicit verification record) that names the
  designated primary claim in ``depends_on`` — AND a general target statement.

Sketches, experiments, supported claims, and solver exit statuses can never
produce either label. ``VERIFIED_REDUCTION`` has no honest automatic signal yet
and is never auto-derived; it is reserved for explicit assignment by a future
campaign workflow.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from opentorus.research.dossier.models import EvidenceRecord

TargetScope = Literal["general", "fixed_instance", "unclear"]

TERMINAL_CLASSIFICATIONS: tuple[str, ...] = (
    "GENERAL_CONJECTURE_PROVED",
    "GENERAL_CONJECTURE_REFUTED",
    "VERIFIED_PARTIAL_THEOREM",
    "VERIFIED_REDUCTION",
    "VERIFIED_COUNTEREXAMPLE_TO_AUXILIARY_CLAIM",
    "COMPUTATIONAL_EVIDENCE",
    "NUMERICAL_EVIDENCE",
    "FAILED_ATTEMPT",
    "INCONCLUSIVE",
    "STATUS_UNCERTAIN",
)

# Unbounded quantifiers / universal structure — the marks of a general target.
_GENERAL = re.compile(
    r"\bfor (?:every|all|each|arbitrary)\b"
    r"|\bevery (?:graph|matrix|polytope|polynomial|integer|tree|digraph|sequence|set)\b"
    r"|\buniversal constant\b"
    r"|\binfinitely many\b"
    r"|\ball sufficiently large\b"
    r"|\basymptotic",
    re.I,
)

# A fixed-instance ask: one parameter value, one order, one record target.
_FIXED = re.compile(
    r"\b(?:scope|order|degree|dimension|length|size|rank)\s*(?:at most|at least|<=|>=|≤|≥|=)\s*\d+"
    r"|\bn\s*=\s*\d+\b"
    r"|\b\d+\s*[x×]\s*\d+\b"
    r"|\bup to \d+\b",
    re.I,
)


def classify_target(statement: str) -> TargetScope:
    """Classify a target statement as general, fixed-instance, or unclear.

    A general quantifier wins over fixed-instance mentions: a general conjecture
    legitimately *names* instances as internal tools ("verified for n ≤ 8").
    Only a statement with fixed-instance asks and no general quantifier is a
    fixed-instance target — the shape the scope policy rejects as a primary
    dossier target.
    """
    text = statement or ""
    if _GENERAL.search(text):
        return "general"
    if _FIXED.search(text):
        return "fixed_instance"
    return "unclear"


def _numerical_evidence_rationale(evidence: list[EvidenceRecord]) -> str:
    """Direction-aware NUMERICAL_EVIDENCE rationale — honest about what the runs showed.

    "Experiments support claims" was direction-blind: it was emitted even when the
    strongest succeeded experiment purported to *refute* the claim, or when no
    evidence was linked to any claim at all. The wording now states what the linked
    evidence actually says; only linked supporting evidence with nothing contradicting
    earns the word "support".
    """
    if any(e.direction == "contradicts" for e in evidence):
        return (
            "experiments/computations are recorded, including contradicting evidence; "
            "nothing is verification-grade"
        )
    if not evidence:
        return (
            "experiments/computations are recorded (no evidence linked to any claim); "
            "nothing is verification-grade"
        )
    if any(e.direction == "supports" for e in evidence):
        return "recorded experiments/computations support claims; nothing is verification-grade"
    return (
        "experiments/computations are recorded (linked evidence is neutral); "
        "nothing is verification-grade"
    )


def classify_outcome(ot_dir: Path, problem_id: str) -> tuple[str, str]:
    """Derive the campaign-level terminal classification for a dossier.

    Returns ``(label, rationale)`` where ``label`` is one of
    ``TERMINAL_CLASSIFICATIONS``. Purely derived from existing artifacts —
    conservative by construction: when in doubt it classifies *down*, and the
    two resolving labels require the designated primary claim (see module
    docstring).
    """
    from opentorus.research.dossier import store
    from opentorus.research.dossier.experiments import list_problem_experiments
    from opentorus.research.epistemics import is_verification_evidence

    dossier = store.require_dossier(ot_dir, problem_id)
    statement = store.read_statement(ot_dir, problem_id) or dossier.title
    scope = classify_target(statement)
    claims = store.list_claims(ot_dir, problem_id)
    evidence = store.list_evidence(ot_dir, problem_id)
    experiments = list_problem_experiments(ot_dir, problem_id)
    failed = store.list_failed_attempts(ot_dir, problem_id)

    primary = None
    if dossier.primary_claim_id:
        primary = next((c for c in claims if c.id == dossier.primary_claim_id), None)

    if primary is not None:
        if primary.status == "formally_verified":
            if scope == "general":
                return (
                    "GENERAL_CONJECTURE_PROVED",
                    f"designated primary claim {primary.id} is formally_verified and the "
                    "target statement is general",
                )
            return (
                "VERIFIED_PARTIAL_THEOREM",
                f"primary claim {primary.id} is formally_verified, but the target statement "
                f"is {scope} — a non-general target cannot resolve a general campaign",
            )
        counterexample = next(
            (
                c
                for c in claims
                if c.type == "COUNTEREXAMPLE_VERIFIED" and primary.id in c.depends_on
            ),
            None,
        )
        if counterexample is not None:
            if scope == "general":
                return (
                    "GENERAL_CONJECTURE_REFUTED",
                    f"verified counterexample {counterexample.id} targets the designated "
                    f"primary claim {primary.id}",
                )
            return (
                "VERIFIED_COUNTEREXAMPLE_TO_AUXILIARY_CLAIM",
                f"verified counterexample {counterexample.id} refutes {primary.id}, but the "
                f"target statement is {scope}",
            )

    # No settled primary designation — classify by the strongest artifact present.
    if any(c.status == "formally_verified" for c in claims):
        return (
            "VERIFIED_PARTIAL_THEOREM",
            "a formally verified claim exists, but it is not the designated primary claim",
        )
    if any(c.type == "COUNTEREXAMPLE_VERIFIED" for c in claims):
        return (
            "VERIFIED_COUNTEREXAMPLE_TO_AUXILIARY_CLAIM",
            "a verified counterexample exists, but it does not target the designated primary claim",
        )
    if any(is_verification_evidence(e.type) and e.direction == "supports" for e in evidence):
        return (
            "COMPUTATIONAL_EVIDENCE",
            "verification-grade evidence (formal proof / validated numerics) supports a "
            "claim without settling the target",
        )
    if any(e.status == "succeeded" for e in experiments) or any(
        e.type in ("EXPERIMENT", "COMPUTATION") for e in evidence
    ):
        return ("NUMERICAL_EVIDENCE", _numerical_evidence_rationale(evidence))
    if failed or any(c.type == "FORMAL_PROOF_FAILED" for c in claims):
        return (
            "FAILED_ATTEMPT",
            "failed attempts are recorded and no positive artifact goes beyond them",
        )
    if claims or evidence:
        return (
            "INCONCLUSIVE",
            "claims or evidence exist but none reach an evidence- or verification-grade signal",
        )
    return (
        "STATUS_UNCERTAIN",
        "no claims, evidence, or experiments are recorded for this dossier yet",
    )
