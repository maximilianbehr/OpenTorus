"""``campaign import-research``: a legacy ``research`` run as an exploration campaign.

The autonomous research loop predates campaigns; its state (``research/<slug>.json``),
its journal entries (``journal/journal.jsonl``, one per iteration) and its progress
note stay exactly where and how they are — the importer only *reads* them (a test
compares their sha256 before and after). What it writes is a new campaign under the
problem the run belongs to, replaying the journal through the real phase machine
(one work item per ``JournalEntry``, artifact references from its evidence ids, claim
id and the ``EXP-*`` ids its actions mention) and stamping the provenance as the
first event after creation: ``migration_recorded`` with the source paths, their
sha256s, the import time and the importer version. The campaign record carries
``imported_from="research:<slug>"``; a second import of the same run is refused
unless ``force`` (then a further campaign is created, never a rewrite).

The problem is resolved in this order: an explicit ``problem_id``, the research
target claim's ``problem_id``, the active problem — a run that cannot be attributed
to any dossier is refused with the fix spelled out, because campaigns live under a
dossier.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from opentorus.campaign import events as ev
from opentorus.campaign.clock import Clock, SystemClock
from opentorus.campaign.models import CampaignRecord
from opentorus.campaign.research_bridge import (
    IterationFacts,
    ResearchCampaignRecorder,
    find_campaign_by_import_tag,
    imported_from_tag,
)
from opentorus.config import Config
from opentorus.errors import OpenTorusError

IMPORTER_VERSION = "1"


@dataclass
class ImportReport:
    record: CampaignRecord
    campaign_id: str
    problem_id: str
    slug: str
    entries: int
    source_paths: list[str] = field(default_factory=list)
    completed: bool = False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_problem(ot_dir: Path, *, target_claim_id: str | None, problem_id: str | None) -> str:
    from opentorus.research.claims import get_claim
    from opentorus.research.dossier import store as dstore

    if problem_id:
        pid = dstore.canonical_problem_id(problem_id) or problem_id.strip().upper()
        dstore.require_dossier(ot_dir, pid)
        return pid
    if target_claim_id:
        claim = get_claim(ot_dir, target_claim_id)
        if claim is not None and claim.problem_id:
            candidate = claim.problem_id.strip().upper()
            if dstore.get_dossier(ot_dir, candidate) is not None:
                return candidate
    active = dstore.get_active_problem(ot_dir)
    if active is not None and dstore.get_dossier(ot_dir, active) is not None:
        return active
    raise OpenTorusError(
        "This research run is not attributed to any problem dossier and no problem is "
        "active. Pass --problem PROBLEM-XXXX (create one with `opentorus problem new`) so "
        "the imported campaign has a dossier to live under."
    )


def import_research_state(
    ot_dir: Path,
    *,
    question: str | None = None,
    slug: str | None = None,
    clock: Clock | None = None,
    config: Config | None = None,
    problem_id: str | None = None,
    force: bool = False,
) -> CampaignRecord:
    """Replay a legacy research run into a new exploration campaign; originals untouched.

    Returns the new campaign's record; :func:`import_research` returns the fuller report
    (entry count, source paths, whether the campaign was completed)."""
    return import_research(
        ot_dir,
        question=question,
        slug=slug,
        clock=clock,
        config=config,
        problem_id=problem_id,
        force=force,
    ).record


def import_research(
    ot_dir: Path,
    *,
    question: str | None = None,
    slug: str | None = None,
    clock: Clock | None = None,
    config: Config | None = None,
    problem_id: str | None = None,
    force: bool = False,
) -> ImportReport:
    """The importer proper (see :func:`import_research_state`)."""
    from opentorus.agent.research_loop import load_state, load_state_by_slug
    from opentorus.config import default_config
    from opentorus.research.journal import journal_path, list_entries

    if not question and not slug:
        raise OpenTorusError("Pass the research QUESTION or --slug SLUG to import.")
    state = load_state(ot_dir, question) if question else load_state_by_slug(ot_dir, slug or "")
    if state is None:
        from opentorus.agent.research_loop import list_states

        known = ", ".join(s.slug for s in list_states(ot_dir)) or "(none)"
        raise OpenTorusError(
            f"No research state for {question or slug!r} under {ot_dir / 'research'}. "
            f"Known investigations: {known}."
        )
    tag = imported_from_tag(state.slug)
    existing = find_campaign_by_import_tag(ot_dir, tag)
    if existing and not force:
        cids = ", ".join(cid for _pid, cid in existing)
        raise OpenTorusError(
            f"Research run '{state.slug}' was already imported as {cids}. Pass --force to "
            "import it again as a further campaign (the existing one is never rewritten)."
        )
    pid = _resolve_problem(ot_dir, target_claim_id=state.target_claim_id, problem_id=problem_id)
    clock = clock or SystemClock()
    cfg = config or default_config()
    entries = list_entries(ot_dir, investigation=state.slug)

    state_path = ot_dir / "research" / f"{state.slug}.json"
    sources = [state_path]
    jpath = journal_path(ot_dir)
    if jpath.is_file():
        sources.append(jpath)
    if state.progress_path and (ot_dir / state.progress_path).is_file():
        sources.append(ot_dir / state.progress_path)
    source_paths = [str(p.relative_to(ot_dir)) for p in sources]
    sha256s = [_sha256(p) for p in sources]
    imported_at = clock.now()
    provenance: dict[str, object] = {
        "importer": "campaign.importer",
        "importer_version": IMPORTER_VERSION,
        "source_paths": source_paths,
        "sha256s": sha256s,
        "imported_at": imported_at.isoformat(),
        "research_status": state.status,
        "research_stopped_reason": state.stopped_reason,
        "completed_iterations": state.completed_iterations,
        "journal_entries": len(entries),
        "target_claim_id": state.target_claim_id,
    }
    recorder = ResearchCampaignRecorder(ot_dir, cfg, problem_id=pid, clock=clock, actor="importer")
    store = recorder.ensure_campaign(
        slug=state.slug,
        question=state.question,
        imported_from=tag,
        migration_provenance=provenance,
        created_by="importer",
        reuse_existing=False,
        migration=ev.MigrationRecordedPayload(
            source_paths=source_paths,
            sha256s=sha256s,
            imported_at=imported_at,
            importer_version=IMPORTER_VERSION,
        ),
    )
    for entry in entries:
        recorder.record_facts(
            IterationFacts(
                iteration=entry.iteration,
                goal=entry.goal or f"Iteration {entry.iteration}: advance '{state.question}'.",
                actions=tuple(entry.actions),
                evidence_ids=tuple(entry.evidence_ids),
                claim_id=entry.claim_id,
                claim_status=entry.claim_status,
                next_step=entry.next_step,
            ),
            slug=state.slug,
            question=state.question,
        )
    completed = False
    if state.status in ("completed", "stopped"):
        reason = state.stopped_reason or state.status
        recorder.finish(f"research run stopped: {reason}")
        completed = True
    record = store.record()
    return ImportReport(
        record=record,
        campaign_id=store.campaign_id,
        problem_id=pid,
        slug=state.slug,
        entries=len(entries),
        source_paths=source_paths,
        completed=completed,
    )


__all__ = ["IMPORTER_VERSION", "ImportReport", "import_research", "import_research_state"]
