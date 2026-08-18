"""The critic: adversarial review of what a round produced, recorded — never enacted.

Two deterministic reviewers, both already in the codebase, are run over the round's
new artifacts and their outputs are reported as :class:`ReviewRef` s (the engine emits
``review_requested`` / ``review_recorded``):

* ``agent.review.review_target`` for every new *workspace* claim (``CLAIM-*`` in
  ``memory/claims.jsonl`` — the branch-level target claims the falsifier and the
  numerical experimenter record evidence against); its findings and verdict are
  persisted as ``REVIEW-*`` with a graph edge when the verdict is not a pass;
* ``dossier.referee.referee_review(persist=True)`` over the dossier whenever a new
  dossier claim or proof attempt appeared — the hostile referee's ``REFEREE-*``
  report (classifications, overclaims, contradictions) is the campaign's record of
  how the round's proof work holds up.

The critic never applies downgrades (``apply_downgrades=False``) and never touches a
claim status: a review is a finding, and the dossier's own rules decide what follows.
It is deterministic on purpose — reviews must be reproducible and tied to artifacts —
so it makes no model call in either provider mode.
"""

from __future__ import annotations

from opentorus.campaign.models import (
    CostTotals,
    ReviewRef,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import WorkerRuntime


class CriticWorker:
    role = WorkerRole.critic

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.agent.review import review_target
        from opentorus.research.claims import get_claim
        from opentorus.research.dossier import store
        from opentorus.research.dossier.referee import referee_review

        pid = ctx.root_problem.problem_id
        reviews: list[ReviewRef] = []
        notes: list[str] = []
        dossier_targets: list[str] = []
        for target in ctx.review_targets:
            tid = target.strip().upper()
            if tid.startswith("CLAIM-") and get_claim(rt.ot_dir, tid) is not None:
                try:
                    review = review_target(rt.ot_dir, tid)
                except Exception as exc:  # noqa: BLE001 - one bad target must not stop the rest
                    notes.append(f"{tid}: review failed ({exc})")
                    continue
                reviews.append(
                    ReviewRef(
                        review_id=review.id, target_id=tid, kind="review", verdict=review.verdict
                    )
                )
                notes.append(f"{tid}: {review.id} verdict {review.verdict}")
            elif tid.startswith(("CLAIM-", "PROOF-")):
                dossier_targets.append(tid)
        if dossier_targets and store.get_dossier(rt.ot_dir, pid) is not None:
            try:
                report = referee_review(rt.ot_dir, pid, persist=True)
            except Exception as exc:  # noqa: BLE001 - the referee must never break a run
                notes.append(f"referee unavailable: {exc}")
            else:
                reviews.append(
                    ReviewRef(
                        review_id=report.id, target_id=pid, kind="referee", verdict=report.verdict
                    )
                )
                notes.append(
                    f"referee {report.id}: verdict {report.verdict}, "
                    f"{len(report.overclaims)} overclaim(s), "
                    f"{len(report.contradictions)} contradiction(s), "
                    f"{len(report.downgrades_recommended)} downgrade(s) recommended (not applied)"
                )
        if not reviews and not notes:
            notes.append("nothing to review this round")
        return WorkerResult(status="completed", reviews=reviews, notes=notes, usage=CostTotals())


__all__ = ["CriticWorker"]
