"""Read-only dossier facts the engine and the status view consult.

The root mathematical status is *derived* here from dossier artifacts on every call
(``scope.classify_outcome`` for the campaign-level label, ``status_gate.derive_status``
for the report status) and never stored in campaign state — so it cannot go stale
and the campaign cannot upgrade it. A dossier that cannot be classified (missing,
corrupt) yields ``STATUS_UNCERTAIN`` with the error as rationale rather than raising:
a status view must never crash because a ledger is broken.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from opentorus.campaign.models import CampaignSnapshot
from opentorus.campaign.phases import DossierFacts
from opentorus.config import Config
from opentorus.errors import OpenTorusError


class RootMathStatus(BaseModel):
    """What the dossier artifacts say about the problem — separate from campaign status."""

    label: str = "STATUS_UNCERTAIN"
    rationale: str = ""
    report_status: str = "UNSOLVED"
    report_rationale: str = ""
    primary_claim_id: str | None = None
    target_scope: str = "unclear"


def root_math_status(ot_dir: Path, problem_id: str) -> RootMathStatus:
    from opentorus.research.dossier import scope, store
    from opentorus.research.dossier.status_gate import derive_status

    pid = problem_id.strip().upper()
    try:
        dossier = store.require_dossier(ot_dir, pid)
        statement = store.read_statement(ot_dir, pid) or dossier.title
        target = scope.classify_target(statement)
        label, rationale = scope.classify_outcome(ot_dir, pid)
        verdict = derive_status(ot_dir, pid)
    except (OpenTorusError, OSError, ValueError) as exc:
        return RootMathStatus(
            label="STATUS_UNCERTAIN",
            rationale=f"could not derive the dossier status: {exc}",
        )
    return RootMathStatus(
        label=label,
        rationale=rationale,
        report_status=verdict.status,
        report_rationale=verdict.rationale,
        primary_claim_id=dossier.primary_claim_id,
        target_scope=target,
    )


def evidence_count_for(
    ot_dir: Path, problem_id: str, snapshot: CampaignSnapshot | None = None
) -> int:
    """Evidence recorded about the problem: the dossier's own ledger plus workspace
    evidence attributed to the problem or to a claim the campaign targets (the primary
    claim or a branch-level claim). Read-only; a missing ledger counts as zero."""
    from opentorus.research.dossier import store
    from opentorus.research.evidence import list_evidence

    pid = problem_id.strip().upper()
    count = 0
    if store.get_dossier(ot_dir, pid) is not None:
        count += len(store.list_evidence(ot_dir, pid))
    claim_ids: set[str] = set()
    if snapshot is not None:
        if snapshot.normalized_problem and snapshot.normalized_problem.primary_claim_id:
            claim_ids.add(snapshot.normalized_problem.primary_claim_id)
        claim_ids.update(b.target_claim_id for b in snapshot.branches.values() if b.target_claim_id)
    for entry in list_evidence(ot_dir):
        if (entry.problem_id or "").upper() == pid or entry.claim_id in claim_ids:
            count += 1
    return count


def gather_dossier_facts(
    ot_dir: Path,
    problem_id: str,
    snapshot: CampaignSnapshot | None = None,
    *,
    config: Config | None = None,
) -> DossierFacts:
    """The facts a mode's completion criterion and the scheduler need, freshly derived.

    ``config`` (optional) is only used to list the enabled verifier backends — the
    ``verification_backend_changed`` reactivation condition compares against them.
    """
    from opentorus.research.theorems import store as thm_store

    root = root_math_status(ot_dir, problem_id)
    insufficient: tuple[str, ...] = ()
    coverage_ref: str | None = None
    if snapshot is not None:
        insufficient = tuple(snapshot.insufficient_categories)
        coverage_ref = snapshot.coverage_ref
    backends: tuple[str, ...] = ()
    if config is not None:
        from opentorus.tools.research import enabled_verifier_backends

        backends = tuple(enabled_verifier_backends(config))
    pid = problem_id.strip().upper()
    accepted = len(thm_store.list_references(ot_dir, problem_id=pid, review_status="accepted"))
    return DossierFacts(
        root_label=root.label,
        root_rationale=root.rationale,
        report_status=root.report_status,
        insufficient_categories=insufficient,
        coverage_ref=coverage_ref,
        evidence_count=evidence_count_for(ot_dir, pid, snapshot),
        accepted_theorem_ref_count=accepted,
        verifier_backends=backends,
    )


__all__ = ["RootMathStatus", "evidence_count_for", "gather_dossier_facts", "root_math_status"]
