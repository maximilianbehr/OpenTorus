"""The synthesizer: the human-facing outputs at the end of a run.

Writes ``progress.md`` (orchestration state, with the mathematical status derived
separately) and rebuilds the dossier report through ``dossier.report.build_report``
— which runs the honesty linter over what it writes. It never touches a claim status
and treats a report failure as a note, not an error: the campaign still completes.
"""

from __future__ import annotations

from opentorus.campaign.models import CostTotals, WorkerContext, WorkerResult, WorkerRole
from opentorus.campaign.workers.base import WorkerRuntime
from opentorus.errors import OpenTorusError


class SynthesizerWorker:
    role = WorkerRole.synthesizer

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.campaign.progress import write_progress_for
        from opentorus.research.dossier.report import build_report

        notes: list[str] = []
        try:
            path = write_progress_for(rt.ot_dir, ctx.campaign_id, clock=rt.clock)
            notes.append(f"progress written to {path.name}")
        except OpenTorusError as exc:
            notes.append(f"progress not written: {exc}")
        try:
            build_report(rt.ot_dir, ctx.root_problem.problem_id)
            notes.append("dossier report rebuilt (report.md)")
        except OpenTorusError as exc:
            notes.append(f"report not rebuilt: {exc}")
        return WorkerResult(status="completed", notes=notes, usage=CostTotals())


__all__ = ["SynthesizerWorker"]
