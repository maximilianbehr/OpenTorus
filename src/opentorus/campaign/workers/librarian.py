"""The librarian: local literature -> theorem candidates -> coverage for the problem.

Offline and deterministic, so a mock campaign terminates and a real one never waits on
the network for this role. One work item does, in order and bounded:

1. **parse** local papers that were registered but never read (a driver's ``paper add
   PDF`` or a fetch that stopped short leaves ``structure.json`` missing) with the
   existing ``papers.read_paper`` (pypdf, no network) — at most
   :data:`MAX_PARSE_PER_ITEM` per work item, skipping PDFs longer than
   :data:`MAX_PARSE_PAGES` (text extraction on a book takes minutes and a work item is
   one bounded step); each failure is a note, never an exception;
2. **extract** candidate theorem references (``THMREF-*``) from every parsed paper
   that has none yet, attributed to the problem (``extraction.extract_heuristic``:
   candidates only, dedupe by paper + label, so re-runs are idempotent);
3. **assess** coverage (``theorems.coverage.assess_coverage``): candidates make a
   category at most ``partial``, dossier facts at most ``partial``; ``adequate`` needs
   an accepted theorem reference or a human override.

A real run showed why the order matters: the drivers registered PDFs that stayed
unparsed, so the literature branch finished in one step with zero candidates and every
category ``unknown``. It makes no model call, so the engine charges the documented one
step for the work item; the created references are reported as artifacts so the engine
records ``theorem_reference_created`` for each.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.models import (
    ArtifactRef,
    CampaignMode,
    CostTotals,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import WorkerRuntime
from opentorus.errors import OpenTorusError

# Bounds for one work item: parsing is CPU-bound pypdf work; a campaign that registers
# fifty PDFs gets through them across several literature work items, not one.
MAX_PARSE_PER_ITEM = 10
MAX_PARSE_PAGES = 120


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


def _page_count(path: Path) -> int | None:
    """Pages of a PDF from its cross-reference table (cheap; ``None`` when unreadable)."""
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 - a broken PDF is reported by read_paper below
        return None


def parse_local_papers(
    ot_dir: Path, *, limit: int = MAX_PARSE_PER_ITEM, max_pages: int = MAX_PARSE_PAGES
) -> tuple[list[str], list[str]]:
    """Parse registered-but-unread papers with a local file; ``(parsed ids, notes)``.

    Papers without a local file (URL registrations that were never fetched) are left
    alone — fetching is network work this worker never does — and counted in one note.
    """
    from opentorus.research.papers import is_paper_parsed, list_papers, read_paper

    parsed: list[str] = []
    notes: list[str] = []
    unfetched = 0
    attempts = 0
    for paper in sorted(list_papers(ot_dir), key=lambda p: p.id):
        if is_paper_parsed(ot_dir, paper):
            continue
        if not paper.local_path or not (ot_dir / paper.local_path).is_file():
            unfetched += 1
            continue
        if attempts >= limit:
            notes.append(f"{paper.id}: left unparsed (parse cap {limit} per work item reached)")
            continue
        attempts += 1
        pages = _page_count(ot_dir / paper.local_path)
        if pages is not None and pages > max_pages:
            notes.append(f"{paper.id}: skipped ({pages} pages > {max_pages}); parse it by hand")
            continue
        try:
            read_paper(ot_dir, paper.id)
        except OpenTorusError as exc:
            notes.append(f"{paper.id}: parse failed: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - corrupt / non-PDF bytes must not end the item
            notes.append(f"{paper.id}: parse failed: {type(exc).__name__}: {exc}"[:300])
            continue
        parsed.append(paper.id)
    if unfetched:
        notes.append(
            f"{unfetched} registered paper(s) have no local full text (not fetched); "
            "the librarian never fetches"
        )
    return parsed, notes


def extract_candidates(ot_dir: Path, problem_id: str) -> tuple[list[str], list[str]]:
    """Heuristic ``THMREF-*`` candidates for every parsed paper without any; ``(ids, notes)``.

    Attributed to ``problem_id`` so ``assess_coverage`` (which reads references *for
    the problem*) counts them; the category hints they carry make a category at most
    ``partial``.
    """
    from opentorus.research.papers import is_paper_parsed, list_papers
    from opentorus.research.theorems import store as thm_store
    from opentorus.research.theorems.extraction import extract_heuristic

    created: list[str] = []
    notes: list[str] = []
    for paper in sorted(list_papers(ot_dir), key=lambda p: p.id):
        if not is_paper_parsed(ot_dir, paper):
            continue
        if thm_store.list_references(ot_dir, paper_id=paper.id):
            continue
        try:
            refs = extract_heuristic(ot_dir, paper.id, problem_id=problem_id)
        except OpenTorusError as exc:
            notes.append(f"{paper.id}: extraction skipped: {exc}")
            continue
        if refs:
            created.extend(r.id for r in refs)
            notes.append(f"{paper.id}: {len(refs)} candidate theorem reference(s)")
    return created, notes


class LibrarianWorker:
    role = WorkerRole.librarian

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        pid = ctx.root_problem.problem_id
        parsed, parse_notes = parse_local_papers(rt.ot_dir)
        created, extract_notes = extract_candidates(rt.ot_dir, pid)
        try:
            cov_id, insufficient, critical = assess(
                rt.ot_dir, pid, mode=ctx.mode, campaign_id=ctx.campaign_id
            )
        except OpenTorusError as exc:
            return WorkerResult(
                status="failed",
                error_category="other",
                message=str(exc),
                usage=CostTotals(steps=1),
                artifacts_created=_refs(created, ctx),
                notes=[f"coverage assessment failed: {exc}", *parse_notes, *extract_notes],
            )
        covered = len(critical) - len(insufficient)
        return WorkerResult(
            status="branch_done",
            coverage_ref=cov_id,
            insufficient_categories=insufficient,
            artifacts_created=_refs(created, ctx),
            usage=CostTotals(steps=1),
            notes=[
                f"parsed {len(parsed)} local paper(s)"
                + (f": {', '.join(parsed)}" if parsed else ""),
                f"{len(created)} candidate theorem reference(s) extracted (heuristic; candidates "
                "only, review to accept)",
                *parse_notes,
                *extract_notes,
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


def _refs(created: list[str], ctx: WorkerContext) -> list[ArtifactRef]:
    return [
        ArtifactRef(artifact_id=ref_id, kind="theorem_reference", branch_id=ctx.branch_id)
        for ref_id in created
    ]


__all__ = [
    "MAX_PARSE_PAGES",
    "MAX_PARSE_PER_ITEM",
    "LibrarianWorker",
    "assess",
    "extract_candidates",
    "parse_local_papers",
]
