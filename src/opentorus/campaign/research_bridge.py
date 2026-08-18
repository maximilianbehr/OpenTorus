"""Mirroring an autonomous ``research`` run into an exploration campaign.

``opentorus research`` keeps its own state (``research/<slug>.json``, the journal, the
progress note, checkpoints) and always will. This module adds — **only when asked**
(``research --campaign`` / ``campaign.record_research``) and only when a problem is
attributed — a faithful campaign-shaped record of the same run under that problem:
one exploration campaign with ``imported_from="research:<slug>"``, ONE numerical
branch ("Autonomous research: <question>", root relation ``supporting``), and per
iteration the ``work_item_created`` → ``work_item_scheduled`` → ``worker_started`` →
``artifact_created`` (EXP / EVIDENCE / CLAIM ids) → ``worker_completed`` →
``budget_consumed`` cycle walked through the real phase machine (SCHEDULE → EXECUTE →
CRITIQUE → VERIFY → UPDATE_GRAPH → REALLOCATE → SCHEDULE), so ``campaign status`` /
``verify`` / ``tree`` work on it like on any other campaign. When the research run
stops the campaign is completed with the run's stop reason; if the process dies
mid-run the campaign is left at SCHEDULE — a resumable, non-terminal state.

The same recorder replays a legacy run for :mod:`opentorus.campaign.importer` (one
work item per journal entry), which is why it takes plain values, not live objects.
The recorder never touches a claim status: it only references artifact ids the
research loop already created.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from opentorus.campaign import events as ev
from opentorus.campaign import ids, paths
from opentorus.campaign.budget import budget_from_config
from opentorus.campaign.clock import Clock, SystemClock
from opentorus.campaign.models import (
    ArtifactRef,
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignPhase,
    CampaignRecord,
    CampaignStatus,
    CostTotals,
    NormalizedProblem,
    RootRelation,
    ScoreBreakdown,
    WorkBudget,
    WorkerRole,
    WorkItem,
    WorkItemStatus,
)
from opentorus.campaign.store import CampaignStore
from opentorus.config import Config
from opentorus.errors import OpenTorusError
from opentorus.providers.pool import TaskClass

_EXP_ID = re.compile(r"\bEXP-\d+\b")


@dataclass(frozen=True)
class IterationFacts:
    """What one research iteration produced, as plain values (live run or journal)."""

    iteration: int
    goal: str
    actions: tuple[str, ...] = ()
    experiment_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    claim_id: str | None = None
    claim_status: str | None = None
    next_step: str = ""

    @property
    def artifact_refs(self) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        seen: set[str] = set()

        def add(aid: str | None, kind: str) -> None:
            if aid and aid not in seen:
                seen.add(aid)
                refs.append(ArtifactRef(artifact_id=aid, kind=kind))

        add(self.claim_id, "claim")
        add(self.experiment_id, "experiment")
        for text in self.actions:
            for match in _EXP_ID.findall(text):
                add(match, "experiment")
        for eid in self.evidence_ids:
            add(eid, "evidence")
        return refs


def imported_from_tag(slug: str) -> str:
    return f"research:{slug}"


def find_campaign_by_import_tag(ot_dir: Path, tag: str) -> list[tuple[str, str]]:
    """``(problem_id, campaign_id)`` of every campaign whose ``imported_from`` is ``tag``."""
    found: list[tuple[str, str]] = []
    for pid, cid in paths.list_campaigns(ot_dir):
        try:
            record = CampaignStore(ot_dir, pid, cid).record()
        except OpenTorusError:
            continue
        if record.imported_from == tag:
            found.append((pid, cid))
    return found


@dataclass
class ResearchCampaignRecorder:
    """Writes the campaign mirror of a research run (live) or of its journal (import)."""

    ot_dir: Path
    config: Config
    problem_id: str
    clock: Clock = field(default_factory=SystemClock)
    actor: str = "research"
    _store: CampaignStore | None = field(default=None, init=False, repr=False)
    _branch_id: str | None = field(default=None, init=False, repr=False)

    # -- lifecycle ------------------------------------------------------------------

    @property
    def store(self) -> CampaignStore | None:
        return self._store

    @property
    def campaign_id(self) -> str | None:
        return self._store.campaign_id if self._store is not None else None

    def ensure_campaign(
        self,
        *,
        slug: str,
        question: str,
        imported_from: str | None = None,
        migration_provenance: dict[str, object] | None = None,
        created_by: str = "research",
        reuse_existing: bool = True,
        migration: ev.MigrationRecordedPayload | None = None,
    ) -> CampaignStore:
        """Open the mirror campaign for ``slug`` — the existing non-terminal one when
        there is one (a resumed research run keeps recording into it), else a new one
        walked to SCHEDULE with its single numerical branch active. ``migration`` (the
        importer's provenance) is recorded right after creation, before anything else."""
        if self._store is not None:
            return self._store
        tag = imported_from or imported_from_tag(slug)
        if reuse_existing:
            for pid, cid in find_campaign_by_import_tag(self.ot_dir, tag):
                if pid != self.problem_id.upper():
                    continue
                store = CampaignStore(self.ot_dir, pid, cid, clock=self.clock)
                snap = store.load().snapshot
                if snap.status in (
                    CampaignStatus.completed,
                    CampaignStatus.stopped,
                    CampaignStatus.failed,
                ):
                    continue
                self._store = store
                self._branch_id = next(iter(sorted(snap.branches)), None)
                if snap.phase is not CampaignPhase.SCHEDULE:
                    self._walk_to_schedule(store, question)
                return store
        store = self._create(
            slug=slug,
            question=question,
            tag=tag,
            migration_provenance=migration_provenance,
            created_by=created_by,
        )
        self._store = store
        if migration is not None:
            store.append(ev.EventType.migration_recorded, migration, actor=self.actor)
        self._walk_to_schedule(store, question)
        return store

    def _create(
        self,
        *,
        slug: str,
        question: str,
        tag: str,
        migration_provenance: dict[str, object] | None,
        created_by: str,
    ) -> CampaignStore:
        from opentorus.research.dossier import store as dstore

        pid = self.problem_id.upper()
        dstore.require_dossier(self.ot_dir, pid)
        statement = dstore.read_statement(self.ot_dir, pid)
        cfg = budget_from_config(self.config, mode=CampaignMode.exploration)
        cid = ids.next_campaign_id(self.ot_dir)
        record = CampaignRecord(
            id=cid,
            problem_id=pid,
            mode=CampaignMode.exploration,
            created_at=self.clock.now(),
            statement_sha256=hashlib.sha256(statement.encode("utf-8")).hexdigest(),
            config_snapshot=cfg,
            imported_from=tag,
            migration_provenance=migration_provenance,
            created_by=created_by,
        )
        store = CampaignStore(
            self.ot_dir, pid, cid, clock=self.clock, persist_every_event=cfg.persist_every_event
        )
        store.create(record, actor=self.actor)
        self._store = store
        return store

    def _advance(self, store: CampaignStore, outcome: str, next_phase: CampaignPhase) -> None:
        current = store.snapshot.phase
        store.append(
            ev.EventType.phase_completed,
            ev.PhaseCompletedPayload(phase=current, outcome=outcome, next_phase=next_phase),
            actor=self.actor,
        )
        store.append(
            ev.EventType.phase_entered,
            ev.PhaseEnteredPayload(phase=next_phase, from_phase=current, reason=outcome),
            actor=self.actor,
        )

    def _walk_to_schedule(self, store: CampaignStore, question: str) -> None:
        """CREATED → … → SCHEDULE with the statement ingested, the problem normalized,
        literature explicitly *not* mapped, and the one research branch active."""
        from opentorus.research.dossier import scope
        from opentorus.research.dossier import store as dstore

        pid = store.problem_id
        snap = store.snapshot
        if snap.status is CampaignStatus.created:
            store.append(
                ev.EventType.campaign_started,
                ev.CampaignStartedPayload(
                    problem_id=pid,
                    mode=CampaignMode.exploration,
                    config_snapshot=store.record().config_snapshot,
                ),
                actor=self.actor,
            )
        walk: list[tuple[CampaignPhase, str]] = [
            (CampaignPhase.INGEST, "research run recorded as a campaign"),
            (CampaignPhase.NORMALIZE, "statement ingested from the dossier"),
            (CampaignPhase.MAP_LITERATURE, "problem normalized from dossier facts"),
            (
                CampaignPhase.GENERATE_PORTFOLIO,
                "literature not mapped: opentorus research does not assess coverage",
            ),
            (CampaignPhase.SCHEDULE, "single research branch proposed and activated"),
        ]
        for target, outcome in walk:
            snap = store.snapshot
            if snap.phase is target:
                continue
            if snap.phase is CampaignPhase.SCHEDULE:
                break
            self._advance(store, outcome, target)
            if target is CampaignPhase.INGEST:
                statement = dstore.read_statement(self.ot_dir, pid)
                store.append(
                    ev.EventType.artifact_created,
                    ArtifactRef(
                        artifact_id=pid,
                        kind="problem_statement",
                        digest=hashlib.sha256(statement.encode("utf-8")).hexdigest(),
                    ),
                    actor=self.actor,
                    refs=[pid],
                )
            elif target is CampaignPhase.NORMALIZE:
                dossier = dstore.require_dossier(self.ot_dir, pid)
                raw = dstore.read_statement(self.ot_dir, pid)
                text = dstore.statement_body_for_display(raw).strip() or dossier.title
                store.append(
                    ev.EventType.problem_normalized,
                    NormalizedProblem(
                        problem_id=pid,
                        statement=text,
                        title=dossier.title,
                        target_scope=scope.classify_target(text),
                        assumptions=[
                            a.statement for a in dstore.list_assumptions(self.ot_dir, pid)
                        ],
                        primary_claim_id=dossier.primary_claim_id,
                    ),
                    actor=self.actor,
                )
            elif target is CampaignPhase.GENERATE_PORTFOLIO:
                self._propose_branch(store, question)
        if self._branch_id is None:
            self._branch_id = next(iter(sorted(store.snapshot.branches)), None)

    def _propose_branch(self, store: CampaignStore, question: str) -> None:
        snap = store.snapshot
        if snap.branches:
            self._branch_id = next(iter(sorted(snap.branches)))
            return
        bid = ids.mint(snap.counters, ids.BRANCH_PREFIX)
        branch = BranchRecord(
            branch_id=bid,
            campaign_id=store.campaign_id,
            title=f"Autonomous research: {question}"[:120],
            kind=BranchKind.numerical,
            objective=(
                f"Autonomous research: {question} — bounded counterexample searches and "
                "validated numerics recorded as evidence, never as proof."
            ),
            strategy_summary=(
                "opentorus research iterations: local corpus glance, target claim, "
                "state-aware experiment, evidence, adversarial review, narration."
            ),
            root_relation=RootRelation.supporting,
            status=BranchStatus.proposed,
            priority=1.0,
            estimated_cost=1.0,
            assigned_worker_role=WorkerRole.numerical_experimenter,
            strategy_key="numerical_experiment",
        )
        store.append(ev.EventType.branch_proposed, branch, actor=self.actor, branch_id=bid)
        store.append(
            ev.EventType.branch_activated,
            ev.BranchActivatedPayload(branch_id=bid, priority=1.0, slot=1),
            actor=self.actor,
            branch_id=bid,
        )
        store.write_branch_card(store.snapshot.branches[bid])
        self._branch_id = bid

    # -- per iteration ------------------------------------------------------------------

    def record_iteration(self, state: object, result: object) -> None:
        """Live hook: ``(ResearchState, IterationResult)`` from ``run_research``."""
        slug = str(getattr(state, "slug", "") or "investigation")
        question = str(getattr(state, "question", "") or slug)
        facts = IterationFacts(
            iteration=int(getattr(result, "iteration", 0) or 0),
            goal=str(getattr(result, "goal", "") or f"Iteration of '{question}'"),
            experiment_id=getattr(result, "experiment_id", None),
            evidence_ids=tuple(
                e for e in [getattr(result, "evidence_id", None)] if isinstance(e, str)
            ),
            claim_id=getattr(result, "claim_id", None),
            claim_status=getattr(result, "claim_status", None),
        )
        self.record_facts(facts, slug=slug, question=question)

    def record_facts(self, facts: IterationFacts, *, slug: str, question: str) -> None:
        """One SCHEDULE→…→SCHEDULE cycle for one iteration (live or replayed)."""
        store = self.ensure_campaign(slug=slug, question=question)
        if store.snapshot.phase is not CampaignPhase.SCHEDULE:
            self._walk_to_schedule(store, question)
        bid = self._branch_id
        if bid is None:
            self._propose_branch(store, question)
            bid = self._branch_id
        assert bid is not None
        snap = store.snapshot
        wid = ids.mint(snap.counters, ids.WORK_ITEM_PREFIX)
        session = f"{store.campaign_id}:{bid}:{wid}"
        item = WorkItem(
            work_item_id=wid,
            campaign_id=store.campaign_id,
            branch_id=bid,
            role=WorkerRole.numerical_experimenter,
            task_class=TaskClass.numerical_experiment_design.value,
            objective=facts.goal,
            status=WorkItemStatus.created,
            session_id=session,
            budget=WorkBudget(max_steps=1),
        )
        store.append(
            ev.EventType.work_item_created,
            item,
            actor=self.actor,
            branch_id=bid,
            work_item_id=wid,
            correlation_id=wid,
        )
        store.append(
            ev.EventType.work_item_scheduled,
            ev.WorkItemScheduledPayload(
                work_item_id=wid,
                score=ScoreBreakdown(fairness=1.0, novelty=1.0, total=1.0, tie_break=bid),
                claimed_by="research",
            ),
            actor=self.actor,
            branch_id=bid,
            work_item_id=wid,
            correlation_id=wid,
        )
        self._advance(store, f"{wid} (research iteration {facts.iteration})", CampaignPhase.EXECUTE)
        store.append(
            ev.EventType.worker_started,
            ev.WorkerStartedPayload(
                work_item_id=wid,
                role=WorkerRole.numerical_experimenter,
                session_id=session,
                budget=WorkBudget(max_steps=1),
            ),
            role=WorkerRole.numerical_experimenter,
            actor=self.actor,
            branch_id=bid,
            work_item_id=wid,
            correlation_id=wid,
        )
        refs = facts.artifact_refs
        for ref in refs:
            store.append(
                ev.EventType.artifact_created,
                ref.model_copy(update={"branch_id": bid, "work_item_id": wid}),
                role=WorkerRole.numerical_experimenter,
                refs=[ref.artifact_id],
                actor=self.actor,
                branch_id=bid,
                work_item_id=wid,
                correlation_id=wid,
            )
        notes = list(facts.actions)
        if facts.claim_status:
            notes.append(f"claim status per the research loop's own rules: {facts.claim_status}")
        if facts.next_step:
            notes.append(f"next step: {facts.next_step}")
        store.append(
            ev.EventType.worker_completed,
            ev.WorkerCompletedPayload(
                work_item_id=wid,
                status="completed",
                usage=CostTotals(steps=1, work_items=1),
                artifact_ids=[r.artifact_id for r in refs],
                notes=notes,
            ),
            role=WorkerRole.numerical_experimenter,
            actor=self.actor,
            branch_id=bid,
            work_item_id=wid,
            correlation_id=wid,
        )
        store.append(
            ev.EventType.budget_consumed,
            ev.BudgetConsumedPayload(scope="work_item", ref=wid, steps=1),
            role=WorkerRole.numerical_experimenter,
            actor=self.actor,
            branch_id=bid,
            work_item_id=wid,
            correlation_id=wid,
        )
        for target, outcome in (
            (CampaignPhase.CRITIQUE, "research iteration recorded"),
            (CampaignPhase.VERIFY, "critic ran inside the research loop (REVIEW-*)"),
            (CampaignPhase.UPDATE_GRAPH, "no obligations: research records evidence only"),
            (CampaignPhase.REALLOCATE, "artifact references recorded"),
            (CampaignPhase.SCHEDULE, "single research branch stays active"),
        ):
            self._advance(store, outcome, target)

    # -- end -----------------------------------------------------------------------------

    def finish(self, reason: str) -> None:
        """Complete the mirror campaign (no-op when nothing was recorded)."""
        store = self._store
        if store is None:
            return
        snap = store.snapshot
        if snap.status in (
            CampaignStatus.completed,
            CampaignStatus.stopped,
            CampaignStatus.failed,
        ):
            return
        if snap.phase is not CampaignPhase.SYNTHESIZE:
            if snap.phase not in (CampaignPhase.SCHEDULE, CampaignPhase.REALLOCATE):
                self._walk_to_schedule(store, "")
            self._advance(store, reason, CampaignPhase.SYNTHESIZE)
        store.append(
            ev.EventType.campaign_completed,
            ev.CampaignCompletedPayload(reason=reason, mode_criterion="research_run_stopped"),
            actor=self.actor,
        )


__all__ = [
    "IterationFacts",
    "ResearchCampaignRecorder",
    "find_campaign_by_import_tag",
    "imported_from_tag",
]
