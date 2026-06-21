"""Data models for the credible math dossier (Milestone M1).

A ``ProblemDossier`` is the first-class research artifact for one open
mathematical problem. Everything around it — definitions, assumptions, known
results, related papers, claims, evidence, failed attempts, experiments, and
proof attempts — is a typed, file-based record so the whole research state stays
auditable, reproducible, and honest.

Design invariant: **evidence is not truth**. The type system encodes this. A
claim's ``type`` says what kind of statement it is; its ``status`` says how well
it is backed. Only a verifier artifact may move a claim to
``formally_verified``; only a verification artifact may turn a counterexample
*candidate* into a *verified* counterexample. The models here carry the data;
:mod:`opentorus.research.dossier.validation` enforces the rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- Problem-level enums ------------------------------------------------------

ProblemStatus = Literal[
    "open",
    "refuted",
    "solved_externally",
    "partially_resolved",
    "unknown",
]
PROBLEM_STATUSES: tuple[ProblemStatus, ...] = (
    "open",
    "refuted",
    "solved_externally",
    "partially_resolved",
    "unknown",
)

FormalizationStatus = Literal[
    "informal",
    "semi_formal",
    "lean_ready",
    "lean_checked",
    "coq_ready",
    "coq_checked",
]
FORMALIZATION_STATUSES: tuple[FormalizationStatus, ...] = (
    "informal",
    "semi_formal",
    "lean_ready",
    "lean_checked",
    "coq_ready",
    "coq_checked",
)

# Formalization states that mean a proof assistant actually accepted the work.
FORMALIZATION_CHECKED: frozenset[str] = frozenset({"lean_checked", "coq_checked"})


# --- Claim / evidence enums ---------------------------------------------------

ClaimType = Literal[
    "OBSERVATION",
    "CLAIM",
    "CONJECTURE",
    "LEMMA_ATTEMPT",
    "THEOREM",
    "COUNTEREXAMPLE_CANDIDATE",
    "COUNTEREXAMPLE_VERIFIED",
    "REFERENCE_FACT",
    "FORMAL_PROOF_VERIFIED",
    "FORMAL_PROOF_FAILED",
    # A plausibility argument or empirical regularity that is *not* claimed proven.
    "HEURISTIC",
    # A regularity read off experiments — evidence, never a settled result.
    "EXPERIMENTAL_OBSERVATION",
    # An explicitly recorded unresolved sub-question; tracked, never hidden.
    "OPEN_GAP",
]
CLAIM_TYPES: tuple[ClaimType, ...] = (
    "OBSERVATION",
    "CLAIM",
    "CONJECTURE",
    "LEMMA_ATTEMPT",
    "THEOREM",
    "COUNTEREXAMPLE_CANDIDATE",
    "COUNTEREXAMPLE_VERIFIED",
    "REFERENCE_FACT",
    "FORMAL_PROOF_VERIFIED",
    "FORMAL_PROOF_FAILED",
    "HEURISTIC",
    "EXPERIMENTAL_OBSERVATION",
    "OPEN_GAP",
)

ClaimStatus = Literal[
    "unverified",
    "supported",
    "contradicted",
    "refuted",
    "needs_review",
    "verified",
    "formally_verified",
]
CLAIM_STATUSES: tuple[ClaimStatus, ...] = (
    "unverified",
    "supported",
    "contradicted",
    "refuted",
    "needs_review",
    "verified",
    "formally_verified",
)

EvidenceType = Literal[
    "EXPERIMENT",
    "PAPER",
    "PROOF_SKETCH",
    "FORMAL_PROOF",
    "VALIDATED_NUMERICAL",
    "COMPUTATION",
    "REFERENCE",
    "MANUAL_NOTE",
]
EVIDENCE_TYPES: tuple[EvidenceType, ...] = (
    "EXPERIMENT",
    "PAPER",
    "PROOF_SKETCH",
    "FORMAL_PROOF",
    "VALIDATED_NUMERICAL",
    "COMPUTATION",
    "REFERENCE",
    "MANUAL_NOTE",
)

EvidenceDirection = Literal["supports", "contradicts", "neutral"]

ExperimentStatus = Literal["planned", "running", "succeeded", "failed", "inconclusive"]
EXPERIMENT_STATUSES: tuple[ExperimentStatus, ...] = (
    "planned",
    "running",
    "succeeded",
    "failed",
    "inconclusive",
)

ProofAttemptStatus = Literal[
    "sketch",
    "in_progress",
    "blocked",
    "abandoned",
    "verified",
]

AttackStrategy = Literal[
    "literature_map",
    "special_cases",
    "counterexample_search",
    "symbolic_simplification",
    "numerical_experiment",
    "formalization_attempt",
    "proof_sketch",
    "obstruction_search",
]
ATTACK_STRATEGIES: tuple[AttackStrategy, ...] = (
    "literature_map",
    "special_cases",
    "counterexample_search",
    "symbolic_simplification",
    "numerical_experiment",
    "formalization_attempt",
    "proof_sketch",
    "obstruction_search",
)


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- Models -------------------------------------------------------------------


class ProblemDossier(BaseModel):
    """Metadata for a single open-problem dossier (``problem.yaml``)."""

    id: str
    title: str = ""
    status: ProblemStatus = "open"
    domain: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    formalization_status: FormalizationStatus = "informal"
    known_equivalent_forms: list[str] = Field(default_factory=list)
    known_obstructions: list[str] = Field(default_factory=list)
    minimal_examples: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Definition(BaseModel):
    id: str
    term: str
    definition: str
    source_artifacts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class Assumption(BaseModel):
    id: str
    statement: str
    rationale: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class KnownResult(BaseModel):
    id: str
    statement: str
    # A known result must point at a local source artifact (paper / theorem ref /
    # verified local artifact). Without one it is not "known", just a claim.
    source_artifacts: list[str] = Field(default_factory=list)
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class RelatedPaper(BaseModel):
    id: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    source: str = ""
    # Link to a local PAPER-* artifact when one exists; never invent citations.
    paper_artifact: str | None = None
    relevance: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class TheoremRef(BaseModel):
    """A precise pointer into a paper. Missing metadata is marked, never invented."""

    id: str
    paper_artifact: str
    theorem_number: str | None = None
    page: str | None = None
    section: str | None = None
    statement_summary: str = ""
    exact_quote: str | None = None
    claim_links: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class ClaimRecord(BaseModel):
    """A typed mathematical statement with explicit epistemic status."""

    id: str
    problem_id: str
    type: ClaimType
    statement: str
    status: ClaimStatus = "unverified"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    source_artifacts: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)
    confidence: float | None = None
    notes: str = ""


class ClaimStatusChange(BaseModel):
    """An append-only record of a claim's epistemic-status transition.

    The changelog lets a reader see *how* the dossier's beliefs evolved (e.g.
    ``unverified → supported`` when evidence was linked, or ``→ verified`` when a
    counterexample was confirmed) — useful when resuming work weeks later.
    """

    problem_id: str
    claim_id: str
    from_status: str
    to_status: str
    reason: str = ""
    artifact: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class EvidenceRecord(BaseModel):
    """A piece of evidence linked to a claim. Evidence never verifies a claim."""

    id: str
    problem_id: str
    claim_id: str
    type: EvidenceType
    summary: str = ""
    direction: EvidenceDirection = "supports"
    path: str | None = None
    source_artifacts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class Approach(BaseModel):
    """A structured attack on the problem produced by a strategy template."""

    id: str
    problem_id: str
    strategy: AttackStrategy
    objective: str = ""
    assumptions: list[str] = Field(default_factory=list)
    method: str = ""
    expected_outputs: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    resulting_artifacts: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class FailedAttempt(BaseModel):
    """A failed method — a first-class, reusable research artifact."""

    id: str
    problem_id: str
    attempted_method: str
    summary: str = ""
    reason_failed: str = ""
    artifacts: list[str] = Field(default_factory=list)
    reusable_obstruction: bool = False
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class ExperimentRecord(BaseModel):
    """Reproducible experiment manifest (``experiments/EXP-XXXX/manifest.yaml``)."""

    experiment_id: str
    problem_id: str
    title: str = ""
    command: str = ""
    working_directory: str = "."
    python_version: str = ""
    dependencies_hash: str = ""
    git_commit: str | None = None
    random_seed: int | None = None
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    claim_links: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    result_summary: str = ""
    status: ExperimentStatus = "planned"


class ProofAttempt(BaseModel):
    """A proof sketch or formal attempt. A sketch is never a verified proof."""

    id: str
    problem_id: str
    title: str = ""
    kind: Literal["sketch", "formal"] = "sketch"
    scope: Literal["primary", "exploration"] = "primary"
    status: ProofAttemptStatus = "sketch"
    body_path: str | None = None
    gaps: list[str] = Field(default_factory=list)
    claim_links: list[str] = Field(default_factory=list)
    # Only set when an actual verifier accepted the proof.
    verifier: str | None = None
    verification_artifact: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
