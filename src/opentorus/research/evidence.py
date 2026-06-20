"""Evidence ledger linked to claims.

Evidence is never automatically truth. Adding evidence records an observation
about a claim (its source, direction, strength, and limitations) but never
upgrades the claim's status. Contradictory evidence is preserved alongside
supporting evidence rather than overwriting it, and contradictions surface a
suggestion to review or downgrade the claim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_id, read_jsonl

SourceType = Literal[
    "experiment",
    "paper",
    "log",
    "code",
    "user_review",
    "external",
    "manual_note",
]
Direction = Literal["supports", "contradicts", "mixed", "neutral"]
Strength = Literal["weak", "moderate", "strong"]

VALID_SOURCE_TYPES: tuple[str, ...] = (
    "experiment",
    "paper",
    "log",
    "code",
    "user_review",
    "external",
    "manual_note",
)
VALID_DIRECTIONS: tuple[str, ...] = ("supports", "contradicts", "mixed", "neutral")
VALID_STRENGTHS: tuple[str, ...] = ("weak", "moderate", "strong")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Evidence(BaseModel):
    id: str
    claim_id: str
    source_type: SourceType
    source_id: str | None = None
    summary: str = ""
    direction: Direction = "neutral"
    strength: Strength = "moderate"
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


def evidence_path(ot_dir: Path) -> Path:
    return ot_dir / "evidence.jsonl"


def list_evidence(ot_dir: Path, claim_id: str | None = None) -> list[Evidence]:
    entries = read_jsonl(evidence_path(ot_dir), Evidence)
    if claim_id is not None:
        return [e for e in entries if e.claim_id == claim_id]
    return entries


def get_evidence(ot_dir: Path, evidence_id: str) -> Evidence | None:
    for entry in list_evidence(ot_dir):
        if entry.id == evidence_id:
            return entry
    return None


def add_evidence(
    ot_dir: Path,
    claim_id: str,
    *,
    source_type: str,
    source_id: str | None = None,
    summary: str = "",
    direction: str = "neutral",
    strength: str = "moderate",
    limitations: list[str] | None = None,
) -> tuple[Evidence, str | None]:
    """Add an evidence record for a claim.

    Returns the evidence and an optional advisory note (e.g. a suggestion to
    review the claim when the evidence contradicts it). Never changes the claim's
    status — that requires explicit human review.
    """
    if source_type not in VALID_SOURCE_TYPES:
        raise OpenTorusError(
            f"Invalid source_type '{source_type}'. Valid: {', '.join(VALID_SOURCE_TYPES)}"
        )
    if direction not in VALID_DIRECTIONS:
        raise OpenTorusError(
            f"Invalid direction '{direction}'. Valid: {', '.join(VALID_DIRECTIONS)}"
        )
    if strength not in VALID_STRENGTHS:
        raise OpenTorusError(f"Invalid strength '{strength}'. Valid: {', '.join(VALID_STRENGTHS)}")

    existing = list_evidence(ot_dir)
    evidence = Evidence(
        id=next_id("EVIDENCE", (e.id for e in existing)),
        claim_id=claim_id,
        source_type=source_type,  # type: ignore[arg-type]
        source_id=source_id,
        summary=summary,
        direction=direction,  # type: ignore[arg-type]
        strength=strength,  # type: ignore[arg-type]
        limitations=limitations or [],
    )
    append_jsonl(evidence_path(ot_dir), evidence)

    advisory: str | None = None
    if direction == "contradicts":
        advisory = (
            f"{evidence.id} contradicts {claim_id}. Consider reviewing or downgrading "
            "the claim; contradictory evidence is preserved, not discarded."
        )
    return evidence, advisory
