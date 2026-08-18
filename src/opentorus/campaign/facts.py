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


def gather_dossier_facts(
    ot_dir: Path, problem_id: str, snapshot: CampaignSnapshot | None = None
) -> DossierFacts:
    """The facts a mode's completion criterion needs, freshly derived."""
    root = root_math_status(ot_dir, problem_id)
    insufficient: tuple[str, ...] = ()
    coverage_ref: str | None = None
    if snapshot is not None:
        insufficient = tuple(snapshot.insufficient_categories)
        coverage_ref = snapshot.coverage_ref
    return DossierFacts(
        root_label=root.label,
        root_rationale=root.rationale,
        report_status=root.report_status,
        insufficient_categories=insufficient,
        coverage_ref=coverage_ref,
    )


__all__ = ["RootMathStatus", "gather_dossier_facts", "root_math_status"]
