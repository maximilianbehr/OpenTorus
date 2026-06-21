"""Evidence ledger linked to claims.

Evidence is never automatically truth. Adding evidence records an observation
about a claim (its source, direction, strength, and limitations) but never
upgrades the claim's status. Contradictory evidence is preserved alongside
supporting evidence rather than overwriting it, and contradictions surface a
suggestion to review or downgrade the claim.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_id, read_jsonl

_EXP_ID_RE = re.compile(r"^EXP-\d+$")

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
    # Problem dossier this evidence was recorded under (attribution). None for
    # legacy records or evidence added outside any active problem.
    problem_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


def evidence_path(ot_dir: Path) -> Path:
    return ot_dir / "evidence.jsonl"


def list_evidence(
    ot_dir: Path, claim_id: str | None = None, *, problem_id: str | None = None
) -> list[Evidence]:
    entries = read_jsonl(evidence_path(ot_dir), Evidence)
    if claim_id is not None:
        entries = [e for e in entries if e.claim_id == claim_id]
    if problem_id is not None:
        entries = [e for e in entries if e.problem_id == problem_id]
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
    problem_id: str | None = None,
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

    # Experiment citations must point at a real EXP-* artifact: a hallucinated id
    # (e.g. "EXP-9999" the model never created) can never back a claim. A real but
    # not-yet-run experiment is allowed but surfaces an advisory — citing its
    # *results* before it ran would be dishonest.
    exp_advisory: str | None = None
    if source_type == "experiment" and source_id and _EXP_ID_RE.match(source_id.strip()):
        from opentorus.research.experiments import get_experiment

        exp = get_experiment(ot_dir, source_id.strip())
        if exp is None:
            raise OpenTorusError(
                f"Cannot cite experiment '{source_id}': no such EXP-* artifact in this "
                "workspace. Create and run it (exp_new → exp_run) before citing it."
            )
        from opentorus.research.experiments import is_unmodified_counterexample_template

        if is_unmodified_counterexample_template(ot_dir, exp):
            raise OpenTorusError(
                f"{source_id} still runs the unmodified counterexample-search template "
                "(placeholder predicate 'n*n >= n'); it tests a tautology, not the claim. "
                "Edit run.py to encode the real predicate before citing it as evidence."
            )
        if exp.status not in ("completed", "failed"):
            exp_advisory = (
                f"{source_id} has status '{exp.status}' (not run to completion); its results "
                "are not available yet. Run it before relying on its outcome."
            )

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
        problem_id=problem_id,
    )
    append_jsonl(evidence_path(ot_dir), evidence)

    advisory: str | None = None
    if direction == "contradicts":
        advisory = (
            f"{evidence.id} contradicts {claim_id}. Consider reviewing or downgrading "
            "the claim; contradictory evidence is preserved, not discarded."
        )
    elif exp_advisory is not None:
        advisory = exp_advisory
    return evidence, advisory
