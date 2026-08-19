"""The verifier-coordinator: proposes obligation closures — only ones an artifact backs.

The coordinator never verifies anything itself and never touches a claim status. For
each open obligation it asks :func:`opentorus.campaign.proof_tree.settlement.can_close_obligation`
— the single source of truth for closure — whether an *accepted* artifact of a class
the obligation admits exists:

* certificate modes: a ``PROOF-*`` in the workspace verifier ledger passing the same
  four checks as ``dossier.claims._require_verification_artifact`` (exists, not
  inconclusive, accepted, recorded under this problem or unscoped), backend matching
  the mode;
* ``accepted_counterexample_certificate``: a cited ``COUNTEREXAMPLE_VERIFIED`` claim
  whose verification record names every root assumption;
* ``nl_proof_referee_accepted``: a gap-free primary proof attempt linked to the
  obligation's claim, with the gap's closure documented, on which the hostile
  referee passes;
* ``accepted_literature_theorem``: a human-accepted ``THMREF-*`` with an accepted
  applicability check targeting the obligation or its claim.

Anything else stays open with the reasons as notes. With no obligations the
coordinator completes with an empty proposal list. The engine turns proposals into
``obligation_closed`` events; closing an obligation never changes the problem's
derived status.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.models import (
    ClosureProposal,
    CostTotals,
    Obligation,
    ObligationStatus,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import WorkerRuntime


def closure_candidates(
    ot_dir: Path, problem_id: str, obligations: list[Obligation]
) -> tuple[list[ClosureProposal], list[str]]:
    """Closure proposals for the open obligations that an accepted artifact backs.

    Closed / contradicted / abandoned obligations are skipped; every reason the
    settlement rules checked is returned as a note so a "stays open" is explainable.
    """
    from opentorus.campaign.proof_tree.settlement import can_close_obligation

    pid = problem_id.strip().upper()
    proposals: list[ClosureProposal] = []
    notes: list[str] = []
    for ob in obligations:
        if ob.status is not ObligationStatus.open and ob.status is not ObligationStatus.in_progress:
            continue
        verdict = can_close_obligation(ot_dir, pid, ob)
        notes.extend(verdict.details)
        if verdict.allowed and verdict.mode is not None and verdict.artifact_id:
            proposals.append(
                ClosureProposal(
                    obligation_id=ob.obligation_id,
                    artifact_id=verdict.artifact_id,
                    mode=verdict.mode,
                    check_id=verdict.check_id,
                    verdict=verdict.reason,
                )
            )
        else:
            notes.append(f"{ob.obligation_id}: stays open (no accepted artifact backs a closure)")
    return proposals, notes


class VerifierCoordinatorWorker:
    role = WorkerRole.verifier_coordinator

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        proposals, notes = closure_candidates(
            rt.ot_dir, ctx.root_problem.problem_id, list(ctx.open_obligations)
        )
        return WorkerResult(
            status="completed",
            closure_proposals=proposals,
            notes=notes or ["no open obligations"],
            usage=CostTotals(),
        )


__all__ = ["VerifierCoordinatorWorker", "closure_candidates"]
