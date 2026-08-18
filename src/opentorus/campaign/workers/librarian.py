"""The librarian: literature coverage for the problem.

M3 behaviour is offline and deterministic: it runs
``research.theorems.coverage.assess_coverage`` (dossier facts → at most ``partial``;
``adequate`` needs an accepted theorem reference or a human override) and returns
``branch_done`` with the ``COV-`` id. It makes no model call, so the engine charges
the documented one step for the work item (offline campaigns must still terminate).
M6 extends the same worker with candidate theorem extraction from local papers.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.models import (
    CampaignMode,
    CostTotals,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import WorkerRuntime
from opentorus.errors import OpenTorusError


def assess(
    ot_dir: Path, problem_id: str, *, mode: CampaignMode | str, campaign_id: str | None
) -> tuple[str, list[str], list[str]]:
    """``(coverage_ref, insufficient, critical)`` from a persisted assessment."""
    from opentorus.research.theorems.coverage import assess_coverage

    assessment = assess_coverage(
        ot_dir, problem_id, mode=str(mode), campaign_id=campaign_id, persist=True
    )
    return (
        assessment.id,
        [c.value for c in assessment.insufficient],
        [c.value for c in assessment.critical_categories],
    )


class LibrarianWorker:
    role = WorkerRole.librarian

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        try:
            cov_id, insufficient, critical = assess(
                rt.ot_dir, ctx.root_problem.problem_id, mode=ctx.mode, campaign_id=ctx.campaign_id
            )
        except OpenTorusError as exc:
            return WorkerResult(
                status="failed",
                error_category="other",
                message=str(exc),
                usage=CostTotals(steps=1),
                notes=[f"coverage assessment failed: {exc}"],
            )
        covered = len(critical) - len(insufficient)
        return WorkerResult(
            status="branch_done",
            coverage_ref=cov_id,
            insufficient_categories=insufficient,
            usage=CostTotals(steps=1),
            notes=[
                f"coverage {cov_id}: {covered}/{len(critical)} critical categories at least "
                "partial from local artifacts",
                (
                    "insufficient: " + ", ".join(insufficient)
                    if insufficient
                    else "no insufficient critical category"
                ),
                "levels above 'partial' need an accepted theorem reference "
                "(theorem review) or a human coverage override",
            ],
        )


__all__ = ["LibrarianWorker", "assess"]
