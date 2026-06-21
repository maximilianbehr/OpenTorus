"""Derived report-status gate for a problem dossier.

The dossier's own ``status`` field (``open`` / ``refuted`` / …) records the
*problem's* state. This module derives, from the artifact graph alone, a separate
**report status** that answers a blunter question: *how strong is what we
actually have?* It exists so a report can never present a pile of proof sketches
as a solution.

The derivation is pure and deterministic — it reads only persisted artifacts and
two optional adversarial inputs (a referee block, an algebra rejection) — so the
same workspace always yields the same verdict. It is intentionally *additive* and
separate from :data:`opentorus.research.dossier.models.ProblemStatus`; it does
not overload that enum.

Statuses (strongest → weakest):

* ``SOLVED`` — a verified proof artifact or a verified/formally-verified THEOREM.
* ``PARTIALLY_SOLVED`` — a *supported* THEOREM/LEMMA, but nothing verified.
* ``HEURISTIC_ONLY`` — only proof sketches and/or HEURISTIC claims support the
  answer; no theorem is even supported.
* ``EXPERIMENTAL_ONLY`` — experiments ran and produced results, but there is no
  proof sketch and no theorem.
* ``UNSOLVED`` — conjectures/observations/open gaps only; no sketch, no run.
* ``INVALID`` — a verified counterexample, a refuted dossier, an algebra
  rejection, or a blocking referee contradiction makes the claimed result wrong.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from opentorus.research.dossier import store
from opentorus.research.dossier.models import ClaimRecord

ReportStatus = Literal[
    "SOLVED",
    "PARTIALLY_SOLVED",
    "HEURISTIC_ONLY",
    "EXPERIMENTAL_ONLY",
    "UNSOLVED",
    "INVALID",
]
REPORT_STATUSES: tuple[ReportStatus, ...] = (
    "SOLVED",
    "PARTIALLY_SOLVED",
    "HEURISTIC_ONLY",
    "EXPERIMENTAL_ONLY",
    "UNSOLVED",
    "INVALID",
)

# Experiment statuses that mean the experiment actually ran and produced output.
_EXPERIMENT_RAN: frozenset[str] = frozenset({"succeeded", "failed", "inconclusive"})
# Claim statuses that mean a result is verified (mirrors epistemics.VERIFIED_STATUSES).
_VERIFIED: frozenset[str] = frozenset({"verified", "formally_verified"})
# Theorem-like claim types whose *support* counts as partial progress.
_THEOREM_LIKE: frozenset[str] = frozenset({"THEOREM", "LEMMA_ATTEMPT"})


class StatusVerdict(BaseModel):
    """The derived report status plus the counts that justify it."""

    status: ReportStatus
    rationale: str
    has_verified_theorem: bool = False
    has_supported_theorem: bool = False
    verified_theorem_ids: list[str] = []
    sketch_count: int = 0
    heuristic_count: int = 0
    experiment_ran_count: int = 0
    experiment_planned_count: int = 0
    open_gap_count: int = 0
    contradiction_count: int = 0


def _open_gap_count(
    ot_dir: Path,
    problem_id: str,
    claims: list[ClaimRecord],
    proofs: list,  # noqa: ANN001
) -> int:
    """Count explicitly recorded open gaps: OPEN_GAP claims plus sketch gaps.

    Sketch gaps are reconciled against the proof body's ``[GAP-n]`` markers (as the
    report does) so a body full of gaps can never be summarized as gap-free.
    """
    from opentorus.research.dossier.nl_proof import explicit_gaps

    n = sum(1 for c in claims if c.type == "OPEN_GAP")
    for p in proofs:
        body = ""
        body_path = getattr(p, "body_path", None)
        if body_path:
            f = store.dossier_dir(ot_dir, problem_id) / body_path
            if f.is_file():
                body = f.read_text(encoding="utf-8")
        n += len(explicit_gaps(gaps=list(getattr(p, "gaps", None) or []), body=body))
    return n


def derive_status(
    ot_dir: Path,
    problem_id: str,
    *,
    referee_blocked: bool = False,
    algebra_rejected: bool = False,
) -> StatusVerdict:
    """Derive the report status for a dossier from its persisted artifacts.

    ``algebra_rejected`` is OR-ed with any persisted algebra check that rejected a
    claim, so a refuted optimum drives the status to ``INVALID`` without the caller
    having to thread the flag through.
    """
    from opentorus.research.dossier.algebra_link import has_algebra_rejection

    dossier = store.require_dossier(ot_dir, problem_id)
    algebra_rejected = algebra_rejected or has_algebra_rejection(ot_dir, problem_id)
    claims = store.list_claims(ot_dir, problem_id)
    proofs = store.list_proof_attempts(ot_dir, problem_id)
    experiments = _list_experiments(ot_dir, problem_id)

    verified_theorems = [c for c in claims if c.type == "THEOREM" and c.status in _VERIFIED]
    has_verified_proof = any(p.status == "verified" for p in proofs) or any(
        c.status == "formally_verified" or c.type == "FORMAL_PROOF_VERIFIED" for c in claims
    )
    supported_theorem = any(
        c.type in _THEOREM_LIKE and c.status in ({"supported"} | _VERIFIED) for c in claims
    )
    verified_counterexample = any(c.type == "COUNTEREXAMPLE_VERIFIED" for c in claims)
    contradicted = [c for c in claims if c.status in ("contradicted", "refuted")]

    sketches = [p for p in proofs if p.status != "verified"]
    heuristics = [c for c in claims if c.type in ("HEURISTIC", "EXPERIMENTAL_OBSERVATION")]
    ran = [e for e in experiments if e.status in _EXPERIMENT_RAN]
    planned = [e for e in experiments if e.status == "planned"]

    base = StatusVerdict(
        status="UNSOLVED",
        rationale="",
        has_verified_theorem=bool(verified_theorems),
        has_supported_theorem=supported_theorem,
        verified_theorem_ids=[c.id for c in verified_theorems],
        sketch_count=len(sketches),
        heuristic_count=len(heuristics),
        experiment_ran_count=len(ran),
        experiment_planned_count=len(planned),
        open_gap_count=_open_gap_count(ot_dir, problem_id, claims, proofs),
        contradiction_count=len(contradicted),
    )

    # INVALID — the claimed result is contradicted by a verified artifact or a check.
    if verified_counterexample or dossier.status == "refuted":
        base.status = "INVALID"
        base.rationale = (
            "A verified counterexample / refutation exists; the original claim is false."
        )
        return base
    if algebra_rejected:
        base.status = "INVALID"
        base.rationale = "An algebra check rejected a load-bearing claim (e.g. a false optimum)."
        return base
    if referee_blocked:
        base.status = "INVALID"
        base.rationale = "The referee found a blocking contradiction among the claims."
        return base

    # SOLVED — a verification artifact backs the result.
    if has_verified_proof or verified_theorems:
        base.status = "SOLVED"
        base.rationale = "A verified proof or formally-verified theorem backs the result."
        return base

    # PARTIALLY_SOLVED — a theorem/lemma is supported but nothing is verified.
    if supported_theorem:
        base.status = "PARTIALLY_SOLVED"
        base.rationale = (
            "A theorem/lemma is supported by evidence but not verified; the problem is not closed."
        )
        return base

    # HEURISTIC_ONLY — sketches / heuristic claims, but no theorem support.
    if sketches or heuristics:
        base.status = "HEURISTIC_ONLY"
        base.rationale = (
            "Only proof sketches and/or heuristic claims back the answer; no theorem is "
            "even supported, and nothing is machine-checked."
        )
        return base

    # EXPERIMENTAL_ONLY — experiments ran, but no sketch and no theorem.
    if ran:
        base.status = "EXPERIMENTAL_ONLY"
        base.rationale = (
            "Experiments ran and produced results, but no proof sketch or theorem builds "
            "on them yet; results are evidence, not proof."
        )
        return base

    base.status = "UNSOLVED"
    base.rationale = (
        "No verified proof, supported theorem, proof sketch, or completed experiment; the "
        "problem is open."
    )
    return base


def _list_experiments(ot_dir: Path, problem_id: str):  # noqa: ANN202
    from opentorus.research.dossier.experiments import list_experiments

    return list_experiments(ot_dir, problem_id)
