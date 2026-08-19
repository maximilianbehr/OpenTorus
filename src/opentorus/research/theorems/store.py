"""Workspace-level ledgers for theorem references, relations, applicability checks
and coverage assessments.

Layout under ``<ot_dir>/theorems/``::

    references.jsonl              TheoremReference   (rewritten only by set_review_status)
    relations.jsonl               TheoremRelation    (append-only)
    applicability_checks.jsonl    ApplicabilityCheck (append-only)
    coverage/PROBLEM-XXXX.jsonl   CoverageLedgerLine (append-only: assessments + human overrides)

Ids come from :func:`opentorus.jsonl.next_id` (max suffix + 1) so a corrupt line
can never cause an id collision. ``set_review_status`` is deliberately the only
function that can write ``review_status="accepted"``: extraction (heuristic or
LLM) creates candidates, and a human review promotes them.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_id, read_jsonl, rewrite_jsonl
from opentorus.research.theorems.models import (
    REVIEW_STATUSES,
    ROOT_RELATIONS,
    ApplicabilityCheck,
    CoverageAssessment,
    CoverageCategory,
    CoverageEntry,
    CoverageLedgerLine,
    CoverageLevel,
    TheoremReference,
    TheoremRelation,
    utcnow,
)

# --- Paths -----------------------------------------------------------------------


def theorems_dir(ot_dir: Path) -> Path:
    return ot_dir / "theorems"


def references_path(ot_dir: Path) -> Path:
    return theorems_dir(ot_dir) / "references.jsonl"


def relations_path(ot_dir: Path) -> Path:
    return theorems_dir(ot_dir) / "relations.jsonl"


def applicability_path(ot_dir: Path) -> Path:
    return theorems_dir(ot_dir) / "applicability_checks.jsonl"


def coverage_dir(ot_dir: Path) -> Path:
    return theorems_dir(ot_dir) / "coverage"


def coverage_path(ot_dir: Path, problem_id: str) -> Path:
    return coverage_dir(ot_dir) / f"{_pid(problem_id)}.jsonl"


def _pid(problem_id: str) -> str:
    return problem_id.strip().upper()


# --- References ------------------------------------------------------------------


def list_references(
    ot_dir: Path,
    *,
    problem_id: str | None = None,
    paper_id: str | None = None,
    review_status: str | None = None,
) -> list[TheoremReference]:
    """All references, optionally filtered by problem, paper and review status."""
    refs = read_jsonl(references_path(ot_dir), TheoremReference)
    if problem_id is not None:
        pid = _pid(problem_id)
        refs = [r for r in refs if (r.problem_id or "").upper() == pid]
    if paper_id is not None:
        paper = paper_id.strip().upper()
        refs = [r for r in refs if r.paper_id.upper() == paper]
    if review_status is not None:
        refs = [r for r in refs if r.review_status == review_status]
    return refs


def get_reference(ot_dir: Path, ref_id: str) -> TheoremReference | None:
    wanted = ref_id.strip().upper()
    for ref in list_references(ot_dir):
        if ref.id.upper() == wanted:
            return ref
    return None


def require_reference(ot_dir: Path, ref_id: str) -> TheoremReference:
    ref = get_reference(ot_dir, ref_id)
    if ref is None:
        raise OpenTorusError(f"No theorem reference '{ref_id}'. See `opentorus theorem list`.")
    return ref


def add_reference(ot_dir: Path, ref: TheoremReference) -> TheoremReference:
    """Persist a new reference (id assigned here) after checking its paper exists.

    A reference to a paper that is not a local artifact would be exactly the
    hallucinated authority the dossier rules forbid, so it is refused. A new
    reference can never be born ``accepted``: that status is reserved for
    :func:`set_review_status`.
    """
    from opentorus.research.papers import get_paper

    paper_id = ref.paper_id.strip().upper()
    if get_paper(ot_dir, paper_id) is None:
        raise OpenTorusError(
            f"Cannot add a theorem reference: no local paper '{paper_id}'. "
            "Register/fetch the paper first (paper add / paper fetch)."
        )
    if ref.review_status == "accepted":
        raise OpenTorusError(
            "A new theorem reference cannot be created as 'accepted'; add it as a "
            "candidate and promote it with `opentorus theorem review ... --status accepted`."
        )
    existing = list_references(ot_dir)
    now = utcnow()
    record = ref.model_copy(
        update={
            "id": next_id("THMREF", (r.id for r in existing)),
            "paper_id": paper_id,
            "locator": ref.locator.model_copy(update={"paper_id": paper_id}),
            "problem_id": _pid(ref.problem_id) if ref.problem_id else None,
            "created_at": now,
            "updated_at": now,
        }
    )
    append_jsonl(references_path(ot_dir), record)
    return record


def set_review_status(
    ot_dir: Path,
    ref_id: str,
    status: str,
    note: str = "",
    *,
    categories: list[str] | None = None,
    root_relation: str | None = None,
    problem_id: str | None = None,
) -> TheoremReference:
    """Set a reference's review status (the only path to ``accepted``).

    Review is also where a human classifies the reference, so coverage
    ``categories``, the ``root_relation`` to the problem and the ``problem_id``
    attribution can be set in the same step; ``None`` leaves each untouched.
    """
    if status not in REVIEW_STATUSES:
        raise OpenTorusError(
            f"Unknown review status '{status}'; expected one of {', '.join(REVIEW_STATUSES)}."
        )
    changes: dict[str, object] = {"review_status": status, "review_note": note}
    if categories is not None:
        try:
            changes["categories"] = [CoverageCategory(c.strip()) for c in categories]
        except ValueError as exc:
            raise OpenTorusError(
                f"Unknown coverage category in {categories}; expected values from "
                f"{', '.join(c.value for c in CoverageCategory)}."
            ) from exc
    if root_relation is not None:
        if root_relation not in ROOT_RELATIONS:
            raise OpenTorusError(
                f"Unknown root relation '{root_relation}'; expected one of "
                f"{', '.join(ROOT_RELATIONS)}."
            )
        changes["root_relation"] = root_relation
    if problem_id is not None:
        changes["problem_id"] = _pid(problem_id)
    refs = list_references(ot_dir)
    wanted = ref_id.strip().upper()
    updated: TheoremReference | None = None
    rewritten: list[TheoremReference] = []
    for ref in refs:
        if ref.id.upper() == wanted:
            updated = ref.model_copy(update={**changes, "updated_at": utcnow()})
            rewritten.append(updated)
        else:
            rewritten.append(ref)
    if updated is None:
        raise OpenTorusError(f"No theorem reference '{ref_id}'. See `opentorus theorem list`.")
    rewrite_jsonl(references_path(ot_dir), rewritten)
    return updated


# --- Relations -------------------------------------------------------------------


def list_relations(ot_dir: Path, *, ref_id: str | None = None) -> list[TheoremRelation]:
    """All relations, or those touching ``ref_id`` as source or target."""
    rels = read_jsonl(relations_path(ot_dir), TheoremRelation)
    if ref_id is None:
        return rels
    wanted = ref_id.strip().upper()
    return [r for r in rels if wanted in (r.source_ref.upper(), r.target_ref.upper())]


def add_relation(ot_dir: Path, rel: TheoremRelation) -> TheoremRelation:
    """Persist a relation record (id assigned here). Validation lives in relations.py."""
    existing = list_relations(ot_dir)
    record = rel.model_copy(update={"id": next_id("THMREL", (r.id for r in existing))})
    append_jsonl(relations_path(ot_dir), record)
    return record


# --- Applicability checks --------------------------------------------------------


def list_applicability_checks(
    ot_dir: Path, *, ref_id: str | None = None
) -> list[ApplicabilityCheck]:
    checks = read_jsonl(applicability_path(ot_dir), ApplicabilityCheck)
    if ref_id is None:
        return checks
    wanted = ref_id.strip().upper()
    return [c for c in checks if c.theorem_reference_id.upper() == wanted]


def add_applicability_check(ot_dir: Path, check: ApplicabilityCheck) -> ApplicabilityCheck:
    existing = list_applicability_checks(ot_dir)
    record = check.model_copy(update={"id": next_id("THMAPP", (c.id for c in existing))})
    append_jsonl(applicability_path(ot_dir), record)
    return record


# --- Coverage --------------------------------------------------------------------


def _coverage_lines(ot_dir: Path, problem_id: str) -> list[CoverageLedgerLine]:
    return read_jsonl(coverage_path(ot_dir, problem_id), CoverageLedgerLine)


def _all_coverage_ids(ot_dir: Path) -> Iterable[str]:
    """Every assessment id across all problems' coverage ledgers (for ``next_id``).

    Only the *write* path (:func:`record_coverage`) needs this, and it must scan
    every problem's ledger because COV ids are workspace-wide. It reads the raw
    JSON and plucks ``assessment.id`` instead of validating each line as a
    ``CoverageLedgerLine``: id allocation needs no typed model, and validating
    whole assessments (a dozen entries each) on every write grew linear in the
    ledger size. Unparseable lines are skipped, exactly as ``read_jsonl`` does.
    """
    import json

    base = coverage_dir(ot_dir)
    if not base.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(base.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    assessment = payload.get("assessment")
                    ident = assessment.get("id") if isinstance(assessment, dict) else None
                    if isinstance(ident, str) and ident:
                        ids.append(ident)
        except OSError:
            continue
    return ids


def list_coverage_history(ot_dir: Path, problem_id: str) -> list[CoverageAssessment]:
    return [
        line.assessment
        for line in _coverage_lines(ot_dir, problem_id)
        if line.kind == "assessment" and line.assessment is not None
    ]


def latest_coverage(ot_dir: Path, problem_id: str) -> CoverageAssessment | None:
    history = list_coverage_history(ot_dir, problem_id)
    return history[-1] if history else None


def record_coverage(ot_dir: Path, assessment: CoverageAssessment) -> CoverageAssessment:
    """Append an assessment (COV id assigned workspace-wide) to the problem's ledger."""
    record = assessment.model_copy(
        update={
            "id": next_id("COV", _all_coverage_ids(ot_dir)),
            "problem_id": _pid(assessment.problem_id),
        }
    )
    line = CoverageLedgerLine(kind="assessment", problem_id=record.problem_id, assessment=record)
    append_jsonl(coverage_path(ot_dir, record.problem_id), line)
    return record


def list_coverage_overrides(ot_dir: Path, problem_id: str) -> dict[str, CoverageEntry]:
    """Latest human override per category (later lines win)."""
    overrides: dict[str, CoverageEntry] = {}
    for line in _coverage_lines(ot_dir, problem_id):
        if line.kind == "override" and line.override is not None:
            overrides[line.override.category.value] = line.override
    return overrides


def set_coverage_override(
    ot_dir: Path,
    problem_id: str,
    category: str,
    level: str,
    *,
    evidence_ids: list[str] | None = None,
    note: str = "",
) -> CoverageEntry:
    """Record a human coverage judgement for one category (provenance ``human``)."""
    try:
        cat = CoverageCategory(category)
    except ValueError as exc:
        raise OpenTorusError(
            f"Unknown coverage category '{category}'; expected one of "
            f"{', '.join(c.value for c in CoverageCategory)}."
        ) from exc
    try:
        lvl = CoverageLevel(level)
    except ValueError as exc:
        raise OpenTorusError(
            f"Unknown coverage level '{level}'; expected one of "
            f"{', '.join(c.value for c in CoverageLevel)}."
        ) from exc
    entry = CoverageEntry(
        category=cat,
        level=lvl,
        evidence_ids=[e.strip() for e in (evidence_ids or []) if e.strip()],
        provenance="human",
        note=note,
    )
    pid = _pid(problem_id)
    append_jsonl(
        coverage_path(ot_dir, pid),
        CoverageLedgerLine(kind="override", problem_id=pid, override=entry),
    )
    return entry
