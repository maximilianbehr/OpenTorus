"""Typed records for theorem-level literature (THMREF / THMREL / THMAPP / COV).

Every record is a pydantic model persisted as JSONL by :mod:`store`. Ids are
assigned by the store (``next_id``), so a freshly built model may carry an empty
``id`` until it is added. ``TheoremReference`` tolerates unknown fields
(``extra="allow"``) so a newer schema can still be read by an older build.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The excerpt is a *quotation* of the located source context, kept short on purpose:
# it exists to let a reader confirm the statement, not to replace reading the paper.
EXCERPT_LIMIT = 300

# String values of the campaign ``RootRelation`` enum. Defined locally (as strings)
# so this package does not depend on the campaign engine; the campaign package
# owns the enum and validates against the same values.
ROOT_RELATIONS: tuple[str, ...] = (
    "equivalent",
    "sufficient",
    "necessary",
    "special-case",
    "relaxation",
    "counterexample-route",
    "supporting",
    "unrelated",
    "unknown",
)

ExtractionMethod = Literal["manual", "heuristic", "llm"]
ReviewStatus = Literal["candidate", "accepted", "rejected"]
Provenance = Literal["manual", "heuristic", "llm"]
CoverageProvenance = Literal["derived", "librarian", "human"]
Direction = Literal["forward", "converse"]
PerformedBy = Literal["deterministic", "llm", "human"]

REVIEW_STATUSES: tuple[str, ...] = ("candidate", "accepted", "rejected")


def utcnow() -> datetime:
    return datetime.now(UTC)


class CoverageCategory(StrEnum):
    """What a literature map must cover before an attack on a problem is credible."""

    original_problem_source = "original_problem_source"
    definitions_notation = "definitions_notation"
    strongest_known_positive_results = "strongest_known_positive_results"
    known_negative_results = "known_negative_results"
    known_counterexamples = "known_counterexamples"
    special_cases = "special_cases"
    equivalent_formulations = "equivalent_formulations"
    standard_tools_lemmas = "standard_tools_lemmas"
    recent_developments = "recent_developments"
    survey_synthesis_sources = "survey_synthesis_sources"
    unresolved_gaps = "unresolved_gaps"


class CoverageLevel(StrEnum):
    """How well one category is covered.

    ``adequate`` needs an accepted THMREF or a human override; ``conflicting``
    records accepted references in one category that contradict each other.
    """

    unknown = "unknown"
    missing = "missing"
    partial = "partial"
    adequate = "adequate"
    conflicting = "conflicting"


class TheoremRelationKind(StrEnum):
    depends_on = "depends-on"
    implies = "implies"
    equivalent_to = "equivalent-to"
    generalizes = "generalizes"
    specializes = "specializes"
    contradicts = "contradicts"
    applies_to = "applies-to"
    requires_definition = "requires-definition"


class ApplicabilityResult(StrEnum):
    accepted = "accepted"
    rejected = "rejected"
    inconclusive = "inconclusive"
    needs_human_review = "needs-human-review"


class SourceLocator(BaseModel):
    """Where in a local paper a statement lives.

    ``text.txt`` has no page markers, so ``page`` and ``section`` can only be
    checked against ``structure.json`` when it exists; ``label`` (e.g.
    ``"Theorem 2.1"``) is what is actually located in the parsed corpus.
    """

    paper_id: str
    page: int | None = None
    section: str | None = None
    label: str | None = None
    source_path: str | None = None


class TheoremReference(BaseModel):
    """A located, reviewable pointer to a numbered result in a local paper."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    paper_id: str
    locator: SourceLocator
    theorem_label: str | None = None
    title: str = ""
    # sha256 of the context found in the full parsed corpus at extraction time; an
    # applicability check re-locates the statement and compares, so a re-parsed or
    # replaced source is noticed instead of silently trusted.
    location_hash: str = ""
    excerpt: str = ""
    normalized_statement: str = ""
    assumptions: list[str] = Field(default_factory=list)
    quantifiers: list[str] = Field(default_factory=list)
    conclusion: str = ""
    required_definitions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    problem_id: str | None = None
    root_relation: str | None = None
    categories: list[CoverageCategory] = Field(default_factory=list)
    extraction_method: ExtractionMethod = "manual"
    extracting_model: str | None = None
    routing_decision_id: str | None = None
    review_status: ReviewStatus = "candidate"
    review_note: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    schema_version: int = 1

    @field_validator("excerpt")
    @classmethod
    def _excerpt_is_short(cls, value: str) -> str:
        if len(value) > EXCERPT_LIMIT:
            raise ValueError(
                f"excerpt must be at most {EXCERPT_LIMIT} characters (got {len(value)}); "
                "use locators.clip_excerpt"
            )
        return value

    @field_validator("root_relation")
    @classmethod
    def _known_root_relation(cls, value: str | None) -> str | None:
        if value is not None and value not in ROOT_RELATIONS:
            raise ValueError(
                f"unknown root_relation '{value}'; expected one of {', '.join(ROOT_RELATIONS)}"
            )
        return value


class TheoremRelation(BaseModel):
    """A typed edge between two references (or a reference and a CLAIM-/OBL- id)."""

    id: str = ""
    source_ref: str
    target_ref: str
    relation: TheoremRelationKind
    provenance: Provenance = "manual"
    rationale: str = ""
    review_status: ReviewStatus = "candidate"
    created_at: datetime = Field(default_factory=utcnow)


class CheckItem(BaseModel):
    """One deterministic sub-check of an applicability check.

    ``passed`` is ``None`` when the check could not be evaluated (no data), which
    is reported as such rather than counted as a pass.
    """

    name: str
    passed: bool | None
    detail: str = ""


class ApplicabilityCheck(BaseModel):
    """Does a theorem reference apply to a claim under an assumption context?

    The ``result`` is computed deterministically from ``checks``; a model may only
    attach ``proposed_analysis`` (prose), which never changes the result.
    """

    id: str = ""
    theorem_reference_id: str
    problem_id: str
    target_id: str | None = None
    assumption_context: list[str] = Field(default_factory=list)
    claim_text: str = ""
    direction: Direction = "forward"
    result: ApplicabilityResult = ApplicabilityResult.inconclusive
    checks: list[CheckItem] = Field(default_factory=list)
    mismatches: list[str] = Field(default_factory=list)
    performed_by: PerformedBy = "deterministic"
    proposed_analysis: str | None = None
    human_note: str = ""
    routing_decision_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class CoverageEntry(BaseModel):
    category: CoverageCategory
    level: CoverageLevel = CoverageLevel.unknown
    evidence_ids: list[str] = Field(default_factory=list)
    provenance: CoverageProvenance = "derived"
    note: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class CoverageAssessment(BaseModel):
    """A point-in-time coverage map for one problem (append-only history)."""

    id: str = ""
    problem_id: str
    campaign_id: str | None = None
    mode: str | None = None
    entries: dict[str, CoverageEntry] = Field(default_factory=dict)
    critical_categories: list[CoverageCategory] = Field(default_factory=list)
    insufficient: list[CoverageCategory] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class CoverageLedgerLine(BaseModel):
    """One line of ``coverage/<PROBLEM-ID>.jsonl``: an assessment or a human override.

    Both kinds share one append-only file so the history of "what was assessed"
    and "what a human asserted" stays in one place and in order.
    """

    kind: Literal["assessment", "override"]
    problem_id: str
    assessment: CoverageAssessment | None = None
    override: CoverageEntry | None = None
    created_at: datetime = Field(default_factory=utcnow)
