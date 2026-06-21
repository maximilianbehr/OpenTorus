"""Persisted algebra checks linked to a dossier claim.

An optimization-claim check (``opentorus check-algebra``) becomes a first-class
dossier artifact when run against a specific claim: it is stored as
``algebra/ALG-XXXX.json``, and a *rejected* verdict drives the report status gate
to ``INVALID`` and flags the linked claim for review. This is how a symbolic
refutation of a false optimum reaches the integrity graph instead of staying on
the console.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from opentorus.jsonl import next_sequential_id
from opentorus.research.algebra_check import AlgebraCheckResult
from opentorus.research.dossier import store
from opentorus.research.dossier.models import utcnow


class AlgebraRecord(BaseModel):
    id: str
    problem_id: str
    claim_id: str | None = None
    result: AlgebraCheckResult
    created_at: str = ""


def algebra_dir(ot_dir: Path, problem_id: str) -> Path:
    return store.dossier_dir(ot_dir, problem_id) / "algebra"


def list_algebra_checks(ot_dir: Path, problem_id: str) -> list[AlgebraRecord]:
    d = algebra_dir(ot_dir, problem_id)
    if not d.is_dir():
        return []
    out: list[AlgebraRecord] = []
    for f in sorted(d.glob("ALG-*.json")):
        out.append(AlgebraRecord.model_validate_json(f.read_text("utf-8")))
    return out


def has_algebra_rejection(ot_dir: Path, problem_id: str, *, claim_id: str | None = None) -> bool:
    """True if any persisted algebra check (optionally for a given claim) is ``rejected``."""
    for r in list_algebra_checks(ot_dir, problem_id):
        if r.result.verdict == "rejected" and (claim_id is None or r.claim_id == claim_id):
            return True
    return False


def record_algebra_check(
    ot_dir: Path,
    problem_id: str,
    result: AlgebraCheckResult,
    *,
    claim_id: str | None = None,
) -> AlgebraRecord:
    """Persist an algebra check; on a rejected verdict, flag the linked claim for review."""
    store.require_dossier(ot_dir, problem_id)
    d = algebra_dir(ot_dir, problem_id)
    d.mkdir(parents=True, exist_ok=True)
    rec = AlgebraRecord(
        id=next_sequential_id("ALG", len(list_algebra_checks(ot_dir, problem_id))),
        problem_id=problem_id,
        claim_id=claim_id,
        result=result,
        created_at=utcnow().isoformat(),
    )
    (d / f"{rec.id}.json").write_text(json.dumps(rec.model_dump(), indent=2), encoding="utf-8")

    # A rejection is a contradiction: flag the linked claim for review (logged, not silent).
    if claim_id and result.verdict == "rejected":
        from opentorus.research.dossier.claims import set_claim_status

        claim = store.get_claim(ot_dir, problem_id, claim_id)
        if claim is not None and claim.status not in ("refuted", "contradicted"):
            set_claim_status(ot_dir, problem_id, claim_id, "needs_review")
    return rec
