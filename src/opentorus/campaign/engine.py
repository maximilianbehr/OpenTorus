"""The campaign engine: a thin phase orchestrator over the store and the workers.

One named method per working phase (``_phase_ingest`` … ``_phase_synthesize``),
each doing exactly its phase's work through store events and returning the next
phase; :meth:`CampaignEngine.run` is the loop that walks the table. The engine
never crashes the CLI on a bad transition — the store refuses it and the engine
records ``campaign_failed`` — and it never touches a claim status: everything it
learns about the problem it learns by reading dossier artifacts.

Lifecycle: :meth:`start` validates the request (mode, branches, budgets, the
prove-or-refute primary-claim rule D10), allocates a workspace-unique id, creates the
store and runs; :meth:`resume` is idempotent on terminal campaigns; :meth:`pause` /
:meth:`stop` record their reasons; ``KeyboardInterrupt`` pauses with reason
``interrupted`` and re-raises so the CLI can exit 130.

Determinism: ids are minted from the snapshot's counters, timestamps from the
injected clock, and the mock/offline path performs no network I/O, so two fresh
workspaces produce identical event sequences.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from opentorus.agent.control.events import RunEvent, RunEventSink, TurnCompleted
from opentorus.agent.control.models import ReasonCode
from opentorus.agent.control.phase_machine import InvalidTransition
from opentorus.campaign import events as ev
from opentorus.campaign import ids
from opentorus.campaign.budget import (
    CampaignBudgetPolicy,
    budget_from_config,
    has_positive_budget,
)
from opentorus.campaign.clock import Clock, SystemClock
from opentorus.campaign.facts import gather_dossier_facts
from opentorus.campaign.models import (
    ArtifactRef,
    BranchRecord,
    BranchStatus,
    CampaignConfigSnapshot,
    CampaignMode,
    CampaignNodeState,
    CampaignPhase,
    CampaignRecord,
    CampaignSnapshot,
    CampaignStatus,
    CostTotals,
    NormalizedProblem,
    Obligation,
    ObligationStatus,
    RootRelation,
    RouteSummary,
    WorkBudget,
    WorkerContext,
    WorkerResult,
    WorkerRole,
    WorkItem,
    WorkItemStatus,
)
from opentorus.campaign.phases import (
    ModeProfile,
    is_terminal,
    mode_profile,
)
from opentorus.campaign.portfolio import activate_initial, bootstrap_portfolio
from opentorus.campaign.progress import write_progress
from opentorus.campaign.scheduler import ROLE_TASK_CLASS, select_next
from opentorus.campaign.status import summarize_snapshot
from opentorus.campaign.store import CampaignStore, open_campaign
from opentorus.campaign.workers import DEFAULT_WORKERS, Worker, WorkerRuntime
from opentorus.campaign.workers.base import RegistryFactory, diff_artifacts, snapshot_artifacts
from opentorus.config import Config
from opentorus.errors import OpenTorusError
from opentorus.providers.pool import ProviderPool, TaskClass

_logger = logging.getLogger("opentorus")

PRIMARY_CLAIM_REMEDIATION = (
    'opentorus problem claim {pid} --type CONJECTURE --statement "..." && '
    "opentorus problem verdict {pid} --set-primary CLAIM-XXXX"
)


class CampaignConfigError(OpenTorusError):
    """A ``campaign start`` request the engine refuses (exit 2 in the CLI)."""


@dataclass
class ResumeResult:
    record: CampaignRecord
    snapshot: CampaignSnapshot
    resumed: bool
    message: str


@dataclass
class PhaseOutcome:
    """What a phase handler decided: the next phase (``None`` when the handler itself
    moved the campaign — paused, completed, failed) and a short outcome note."""

    next_phase: CampaignPhase | None
    outcome: str = ""


@dataclass
class _Run:
    store: CampaignStore
    record: CampaignRecord
    profile: ModeProfile

    @property
    def cfg(self) -> CampaignConfigSnapshot:
        return self.record.config_snapshot

    @property
    def pid(self) -> str:
        return self.record.problem_id

    @property
    def cid(self) -> str:
        return self.record.id

    @property
    def snap(self) -> CampaignSnapshot:
        return self.store.snapshot


class _UsageCollector:
    """Folds ``TurnCompleted`` events of a worker's loop into tokens/cost/turns and
    forwards every event to the caller's sink (if any)."""

    def __init__(self, inner: RunEventSink | None) -> None:
        self.inner = inner
        self.turns = 0
        self.tokens = 0
        self.cost_usd = 0.0

    def reset(self) -> None:
        self.turns = 0
        self.tokens = 0
        self.cost_usd = 0.0

    def emit(self, event: RunEvent) -> None:
        if isinstance(event, TurnCompleted):
            self.turns += 1
            self.tokens += event.prompt_tokens + event.completion_tokens
            self.cost_usd += event.cost_usd
        if self.inner is not None:
            try:
                self.inner.emit(event)
            except Exception:  # noqa: BLE001 - a sink must never break the run
                _logger.debug("campaign event sink raised", exc_info=True)


@dataclass
class _ExecuteContext:
    """The per-work-item facts ``_phase_execute`` needs while a worker runs."""

    item: WorkItem
    branch: BranchRecord
    ctx: WorkerContext
    result: WorkerResult = field(default_factory=WorkerResult)
    new_refs: list[ArtifactRef] = field(default_factory=list)
    wall_seconds: float = 0.0


class CampaignEngine:
    """Start, run, pause, resume and stop campaigns for one workspace."""

    def __init__(
        self,
        root: Path,
        ot_dir: Path,
        config: Config,
        *,
        pool: ProviderPool | None = None,
        clock: Clock | None = None,
        event_sink: RunEventSink | None = None,
        worker_registry: dict[WorkerRole, Worker] | None = None,
        stop_flag: Callable[[], bool] | None = None,
        notice: Callable[[str], None] | None = None,
        confirm: object | None = None,
        registry_factory: RegistryFactory | None = None,
    ) -> None:
        self.root = root
        self.ot_dir = ot_dir
        self.config = config
        self.clock: Clock = clock or SystemClock()
        self.event_sink = event_sink
        self.workers: dict[WorkerRole, Worker] = dict(
            worker_registry if worker_registry is not None else DEFAULT_WORKERS
        )
        self._stop_flag = stop_flag
        self._notice = notice or (lambda text: _logger.info("%s", text))
        self._pool = pool
        self._collector = _UsageCollector(event_sink)
        self._confirm = confirm
        self._registry_factory = registry_factory
        self._handlers: dict[CampaignPhase, Callable[[_Run], PhaseOutcome]] = {
            CampaignPhase.INGEST: self._phase_ingest,
            CampaignPhase.NORMALIZE: self._phase_normalize,
            CampaignPhase.MAP_LITERATURE: self._phase_map_literature,
            CampaignPhase.GENERATE_PORTFOLIO: self._phase_generate_portfolio,
            CampaignPhase.SCHEDULE: self._phase_schedule,
            CampaignPhase.EXECUTE: self._phase_execute,
            CampaignPhase.CRITIQUE: self._phase_critique,
            CampaignPhase.VERIFY: self._phase_verify,
            CampaignPhase.UPDATE_GRAPH: self._phase_update_graph,
            CampaignPhase.REALLOCATE: self._phase_reallocate,
            CampaignPhase.SYNTHESIZE: self._phase_synthesize,
        }

    # -- services -------------------------------------------------------------------

    @property
    def pool(self) -> ProviderPool:
        """The provider pool, built lazily on the engine's clock (so routing records
        are as deterministic as the rest of a mock run)."""
        if self._pool is None:
            from opentorus.providers.capabilities import CapabilityCache, default_cache_path

            self._pool = ProviderPool(
                self.config,
                ot_dir=self.ot_dir,
                capability_cache=CapabilityCache(default_cache_path(self.ot_dir)),
                clock=self.clock.now,
            )
        return self._pool

    def _runtime(self, run: _Run) -> WorkerRuntime:
        cfg = run.cfg

        def _should_stop() -> bool:
            if self._stop_flag is not None and self._stop_flag():
                return True
            return CampaignBudgetPolicy(cfg, run.snap.budget).is_exhausted()

        return WorkerRuntime(
            root=self.root,
            ot_dir=self.ot_dir,
            config=self.config,
            pool=self.pool,
            clock=self.clock,
            event_sink=self._collector,
            confirm=self._confirm,  # type: ignore[arg-type]
            registry_factory=self._registry_factory,
            should_stop=_should_stop,
        )

    def _open(self, campaign_id: str) -> _Run:
        store = open_campaign(self.ot_dir, campaign_id, clock=self.clock)
        loaded = store.load()
        return _Run(store=store, record=loaded.record, profile=mode_profile(loaded.record.mode))

    # -- start ----------------------------------------------------------------------

    def start(
        self,
        problem_id: str,
        *,
        mode: CampaignMode | str | None = None,
        branches: int | None = None,
        max_steps: int | None = None,
        token_budget: int | None = None,
        max_wall_seconds: int | None = None,
        cost_budget: float | None = None,
        create_primary_claim: bool = True,
        run: bool = True,
    ) -> CampaignRecord:
        """Validate, create, and (unless ``run=False``) run a new campaign."""
        from opentorus.research.dossier import store as dstore

        pid = dstore.canonical_problem_id(problem_id) or problem_id.strip().upper()
        dossier = dstore.require_dossier(self.ot_dir, pid)
        try:
            resolved_mode = (
                CampaignMode(str(mode))
                if mode is not None
                else CampaignMode(str(self.config.campaign.default_mode))
            )
        except ValueError as exc:
            raise CampaignConfigError(
                f"Unknown campaign mode '{mode}'. Valid modes: "
                + ", ".join(m.value for m in CampaignMode)
                + "."
            ) from exc
        cfg = budget_from_config(
            self.config,
            mode=resolved_mode,
            branches=branches,
            max_steps=max_steps,
            token_budget=token_budget,
            max_wall_seconds=max_wall_seconds,
            cost_budget=cost_budget,
        )
        self._validate_start(cfg)
        primary_created: str | None = None
        if resolved_mode is CampaignMode.prove_or_refute and not dossier.primary_claim_id:
            if not create_primary_claim:
                raise CampaignConfigError(
                    f"prove-or-refute needs a designated primary claim on {pid} and "
                    "--no-primary-claim refused to create one. Designate it yourself: "
                    + PRIMARY_CLAIM_REMEDIATION.format(pid=pid)
                )
            primary_created = self._create_primary_claim(pid)
            dossier = dstore.require_dossier(self.ot_dir, pid)
        statement = dstore.read_statement(self.ot_dir, pid)
        cid = ids.next_campaign_id(self.ot_dir)
        record = CampaignRecord(
            id=cid,
            problem_id=pid,
            mode=resolved_mode,
            created_at=self.clock.now(),
            statement_sha256=hashlib.sha256(statement.encode("utf-8")).hexdigest(),
            config_snapshot=cfg,
            created_by="cli",
            primary_claim_id=dossier.primary_claim_id,
        )
        store = CampaignStore(
            self.ot_dir,
            pid,
            cid,
            clock=self.clock,
            fsync=True,
            persist_every_event=cfg.persist_every_event,
        )
        store.create(record, actor="cli")
        if primary_created is not None:
            store.append(
                ev.EventType.artifact_created,
                ArtifactRef(artifact_id=primary_created, kind="claim"),
                actor="engine",
                refs=[primary_created],
            )
        if cfg.max_parallel_workers > 1:
            store.append(
                ev.EventType.parallelism_capped,
                ev.ParallelismCappedPayload(requested=cfg.max_parallel_workers, effective=1),
            )
        run_ctx = _Run(store=store, record=record, profile=mode_profile(resolved_mode))
        self._write_progress(run_ctx)
        if run:
            self.run(cid)
        return record

    def _validate_start(self, cfg: CampaignConfigSnapshot) -> None:
        for name, value in (
            ("--max-steps", cfg.max_steps),
            ("--token-budget", cfg.token_budget),
            ("--max-wall-seconds", cfg.max_wall_seconds),
            ("--cost-budget", cfg.cost_budget),
        ):
            if value < 0:
                raise CampaignConfigError(f"{name} must be >= 0 (0 = unlimited), got {value}.")
        if cfg.initial_branches < 1:
            raise CampaignConfigError("--branches must be at least 1.")
        if cfg.mode is CampaignMode.prove_or_refute and cfg.initial_branches < 2:
            raise CampaignConfigError(
                "prove-or-refute needs at least 2 branches (a proof route and a "
                f"counterexample route); got --branches {cfg.initial_branches}."
            )
        if not has_positive_budget(cfg):
            raise CampaignConfigError(
                "No positive budget on any axis after merging config and flags: set "
                "--max-steps (or --token-budget / --max-wall-seconds / --cost-budget) to a "
                "positive value, or configure campaign.max_steps; 0 means unlimited and an "
                "unbounded campaign is refused."
            )

    def _create_primary_claim(self, pid: str) -> str:
        """Rule D10: create the CONJECTURE claim from the statement and designate it.

        The claim's status is whatever the dossier's own rules give a new CONJECTURE
        (``unverified``); nothing here changes it, and no ``status_changes`` entry is
        written. The engine is the campaign driver, so designating the target is its job.
        """
        from opentorus.research.dossier import store as dstore
        from opentorus.research.dossier.claims import add_claim

        raw = dstore.read_statement(self.ot_dir, pid)
        statement = (
            dstore.statement_body_for_display(raw).strip()
            or dstore.require_dossier(self.ot_dir, pid).title
        )
        claim = add_claim(
            self.ot_dir,
            pid,
            claim_type="CONJECTURE",
            statement=statement,
            notes=(
                "Created by `opentorus campaign start` (prove-or-refute) from the dossier "
                "statement and designated the primary claim; status untouched."
            ),
        )
        dossier = dstore.require_dossier(self.ot_dir, pid)
        dossier.primary_claim_id = claim.id
        dstore.save_dossier(self.ot_dir, dossier)
        self._notice(
            f"Created {claim.id} (CONJECTURE, status {claim.status}) from the statement of "
            f"{pid} and designated it the primary claim. The status is untouched; only "
            "verification artifacts can move it."
        )
        return claim.id

    # -- lifecycle ------------------------------------------------------------------

    def resume(self, campaign_id: str) -> ResumeResult:
        run = self._open(campaign_id)
        snap = run.snap
        if is_terminal(snap.phase):
            return ResumeResult(
                run.record,
                snap,
                False,
                f"{run.cid} is already {snap.status.value}; nothing to resume.",
            )
        if snap.status is CampaignStatus.paused:
            target = snap.resume_phase
            if target is None or is_terminal(target):
                raise OpenTorusError(
                    f"{run.cid} is paused without a resumable phase (resume_phase={target})."
                )
            run.store.append(
                ev.EventType.campaign_resumed,
                ev.CampaignResumedPayload(
                    from_phase=CampaignPhase.PAUSED,
                    resume_phase=target,
                    note=f"resumed after pause: {snap.pause_reason or ''}".strip(),
                ),
                actor="cli",
            )
            message = f"resumed {run.cid} at phase {target.value}"
        else:
            message = f"continued {run.cid} at phase {snap.phase.value}"
        snapshot = self.run(run.cid)
        return ResumeResult(run.record, snapshot, True, message)

    def pause(self, campaign_id: str, reason: str) -> CampaignSnapshot:
        run = self._open(campaign_id)
        snap = run.snap
        if is_terminal(snap.phase):
            raise OpenTorusError(f"{run.cid} is {snap.status.value}; it cannot be paused.")
        if snap.status is CampaignStatus.paused:
            return snap
        run.store.append(
            ev.EventType.campaign_paused,
            ev.CampaignPausedPayload(reason=reason, resume_phase=snap.phase),
            actor="cli",
        )
        self._write_progress(run)
        return run.snap

    def stop(self, campaign_id: str, reason: str) -> CampaignSnapshot:
        run = self._open(campaign_id)
        snap = run.snap
        if is_terminal(snap.phase):
            raise OpenTorusError(f"{run.cid} is already {snap.status.value}.")
        run.store.append(
            ev.EventType.campaign_stopped, ev.CampaignStoppedPayload(reason=reason), actor="cli"
        )
        self._write_progress(run)
        return run.snap

    # -- the phase loop ---------------------------------------------------------------

    def run(
        self,
        campaign_id: str,
        *,
        until: Callable[[CampaignSnapshot], bool] | None = None,
    ) -> CampaignSnapshot:
        """Walk the phase table until a terminal phase, a pause, or ``until`` says stop."""
        run = self._open(campaign_id)
        try:
            self._loop(run, until)
        except InvalidTransition as exc:
            # The store refused a move the table forbids: record it as a failure so
            # the campaign is inspectable, never a traceback for the CLI.
            self._fail(run, f"invalid phase transition: {exc}")
        except KeyboardInterrupt:
            self._pause_now(run, "interrupted")
            self._write_progress(run)
            raise
        self._write_progress(run)
        return run.snap

    def _loop(self, run: _Run, until: Callable[[CampaignSnapshot], bool] | None) -> None:
        store = run.store
        snap = run.snap
        if snap.status is CampaignStatus.paused and not is_terminal(snap.phase):
            target = snap.resume_phase
            if target is None or is_terminal(target):
                raise OpenTorusError(f"{run.cid} is paused without a resumable phase.")
            store.append(
                ev.EventType.campaign_resumed,
                ev.CampaignResumedPayload(from_phase=CampaignPhase.PAUSED, resume_phase=target),
            )
        while True:
            snap = run.snap
            if is_terminal(snap.phase) or snap.status is CampaignStatus.paused:
                return
            if until is not None and until(snap):
                return
            if self._stop_flag is not None and self._stop_flag():
                self._pause_now(run, "stop requested")
                return
            if snap.phase is CampaignPhase.CREATED:
                if snap.started_at is None:
                    # ``campaign_started`` marks the first time the loop actually runs,
                    # so a ``--no-run`` campaign honestly reads ``created`` until then.
                    store.append(
                        ev.EventType.campaign_started,
                        ev.CampaignStartedPayload(
                            problem_id=run.pid, mode=run.record.mode, config_snapshot=run.cfg
                        ),
                    )
                self._advance(run, "created", CampaignPhase.INGEST)
                continue
            handler = self._handlers.get(snap.phase)
            if handler is None:
                self._fail(run, f"no handler for phase {snap.phase.value}")
                return
            outcome = handler(run)
            if outcome.next_phase is not None:
                self._advance(run, outcome.outcome, outcome.next_phase)

    def _advance(self, run: _Run, outcome: str, next_phase: CampaignPhase) -> None:
        current = run.snap.phase
        run.store.append(
            ev.EventType.phase_completed,
            ev.PhaseCompletedPayload(phase=current, outcome=outcome, next_phase=next_phase),
        )
        run.store.append(
            ev.EventType.phase_entered,
            ev.PhaseEnteredPayload(phase=next_phase, from_phase=current, reason=outcome),
        )

    def _pause_now(self, run: _Run, reason: str) -> None:
        snap = run.snap
        if is_terminal(snap.phase) or snap.status is CampaignStatus.paused:
            return
        try:
            run.store.append(
                ev.EventType.campaign_paused,
                ev.CampaignPausedPayload(reason=reason, resume_phase=snap.phase),
            )
        except OpenTorusError:
            _logger.warning("could not record pause of %s (%s)", run.cid, reason)

    def _fail(self, run: _Run, reason: str) -> None:
        snap = run.snap
        if is_terminal(snap.phase):
            return
        try:
            run.store.append(ev.EventType.campaign_failed, ev.CampaignFailedPayload(reason=reason))
        except OpenTorusError:
            _logger.warning("could not record failure of %s: %s", run.cid, reason)

    def _write_progress(self, run: _Run) -> None:
        try:
            events, _diags = run.store.read_events()
            summary = summarize_snapshot(self.ot_dir, run.snap, events=events)
            write_progress(run.store, summary)
        except (OpenTorusError, OSError) as exc:  # progress is a courtesy, never a blocker
            _logger.warning("could not write progress for %s: %s", run.cid, exc)

    # -- phases -----------------------------------------------------------------------

    def _phase_ingest(self, run: _Run) -> PhaseOutcome:
        """Read the dossier statement and pin its hash as the first artifact reference."""
        from opentorus.research.dossier import store as dstore

        statement = dstore.read_statement(self.ot_dir, run.pid)
        digest = hashlib.sha256(statement.encode("utf-8")).hexdigest()
        run.store.append(
            ev.EventType.artifact_created,
            ArtifactRef(artifact_id=run.pid, kind="problem_statement", digest=digest),
            refs=[run.pid],
        )
        if run.record.statement_sha256 and digest != run.record.statement_sha256:
            outcome = "statement changed since the campaign was created (hash differs)"
        else:
            outcome = "statement ingested; hash matches campaign.yaml"
        return PhaseOutcome(CampaignPhase.NORMALIZE, outcome)

    def _phase_normalize(self, run: _Run) -> PhaseOutcome:
        """Build the NormalizedProblem every worker sees, from dossier facts only."""
        from opentorus.research.dossier import scope
        from opentorus.research.dossier import store as dstore

        dossier = dstore.require_dossier(self.ot_dir, run.pid)
        raw = dstore.read_statement(self.ot_dir, run.pid)
        statement = dstore.statement_body_for_display(raw).strip() or dossier.title
        normalized = NormalizedProblem(
            problem_id=run.pid,
            statement=statement,
            title=dossier.title,
            target_scope=scope.classify_target(statement),
            assumptions=[a.statement for a in dstore.list_assumptions(self.ot_dir, run.pid)],
            definitions=[
                f"{d.term}: {d.definition}" for d in dstore.list_definitions(self.ot_dir, run.pid)
            ],
            primary_claim_id=dossier.primary_claim_id,
        )
        run.store.append(ev.EventType.problem_normalized, normalized)
        return PhaseOutcome(
            CampaignPhase.MAP_LITERATURE,
            f"target scope {normalized.target_scope}; {len(normalized.assumptions)} assumption(s), "
            f"{len(normalized.definitions)} definition(s)",
        )

    def _phase_map_literature(self, run: _Run) -> PhaseOutcome:
        """Assess literature coverage (offline derivation) and record it."""
        from opentorus.campaign.workers.librarian import assess

        cov_id, insufficient, critical = assess(
            self.ot_dir, run.pid, mode=run.record.mode, campaign_id=run.cid
        )
        run.store.append(
            ev.EventType.coverage_assessed,
            ev.CoverageAssessedPayload(
                coverage_ref=cov_id, insufficient=insufficient, critical=critical
            ),
            role=WorkerRole.librarian,
            refs=[cov_id],
        )
        return PhaseOutcome(
            CampaignPhase.GENERATE_PORTFOLIO,
            f"coverage {cov_id}: {len(insufficient)} of {len(critical)} critical categories "
            "insufficient",
        )

    def _phase_generate_portfolio(self, run: _Run) -> PhaseOutcome:
        """Propose and activate branches (M3: the deterministic literature bootstrap)."""
        from opentorus.research.dossier.strategies import STRATEGY_TEMPLATES, create_approach

        snap = run.snap
        proposals = bootstrap_portfolio(
            snap, mode=run.record.mode, coverage=list(snap.insufficient_categories)
        )
        accepted: list[BranchRecord] = []
        for proposal in proposals:
            branch = proposal.model_copy(
                update={"branch_id": ids.mint(run.snap.counters, ids.BRANCH_PREFIX)}
            )
            if branch.strategy_key in STRATEGY_TEMPLATES:
                approach = create_approach(self.ot_dir, run.pid, branch.strategy_key)
                branch.approach_id = approach.id
            run.store.append(ev.EventType.branch_proposed, branch, branch_id=branch.branch_id)
            if branch.approach_id:
                run.store.append(
                    ev.EventType.artifact_created,
                    ArtifactRef(
                        artifact_id=branch.approach_id, kind="approach", branch_id=branch.branch_id
                    ),
                    branch_id=branch.branch_id,
                    refs=[branch.approach_id],
                )
            if run.cfg.require_root_relation and branch.root_relation is RootRelation.unknown:
                run.store.append(
                    ev.EventType.branch_rejected,
                    ev.BranchRejectedPayload(
                        branch_id=branch.branch_id,
                        reason_code="ROOT_RELATION_REQUIRED",
                        note="campaign.require_root_relation is on and the relation is unknown",
                    ),
                    branch_id=branch.branch_id,
                )
                continue
            accepted.append(branch)
            run.store.write_branch_card(run.snap.branches[branch.branch_id])
        for slot, branch in enumerate(
            activate_initial(accepted, max_active=run.cfg.max_active_branches), start=1
        ):
            run.store.append(
                ev.EventType.branch_activated,
                ev.BranchActivatedPayload(
                    branch_id=branch.branch_id, priority=branch.priority, slot=slot
                ),
                branch_id=branch.branch_id,
            )
            run.store.write_branch_card(run.snap.branches[branch.branch_id])
        active = sum(1 for b in run.snap.branches.values() if b.status is BranchStatus.active)
        return PhaseOutcome(
            CampaignPhase.SCHEDULE,
            f"{len(proposals)} proposal(s), {len(accepted)} accepted, {active} active",
        )

    def _phase_schedule(self, run: _Run) -> PhaseOutcome:
        """Pick the next work item, or hand over to synthesis when nothing is runnable."""
        snap = run.snap
        facts = gather_dossier_facts(self.ot_dir, run.pid, snap)
        plan = select_next(
            snap,
            run.cfg.scheduler_weights,
            run.record.mode,
            facts,
            branch_step_budget=run.cfg.branch_step_budget,
        )
        if plan is None:
            return PhaseOutcome(CampaignPhase.SYNTHESIZE, "no runnable work item")
        wid = ids.mint(snap.counters, ids.WORK_ITEM_PREFIX)
        item = WorkItem(
            work_item_id=wid,
            campaign_id=run.cid,
            branch_id=plan.branch_id,
            role=plan.role,
            task_class=plan.task_class,
            objective=plan.objective,
            status=WorkItemStatus.created,
            session_id=f"{run.cid}:{plan.branch_id}:{wid}",
            budget=WorkBudget(max_steps=plan.max_steps),
        )
        run.store.append(
            ev.EventType.work_item_created, item, branch_id=plan.branch_id, work_item_id=wid
        )
        run.store.append(
            ev.EventType.work_item_scheduled,
            ev.WorkItemScheduledPayload(work_item_id=wid, score=plan.score, claimed_by="engine"),
            branch_id=plan.branch_id,
            work_item_id=wid,
        )
        return PhaseOutcome(CampaignPhase.EXECUTE, f"{wid} ({plan.role.value} on {plan.branch_id})")

    def _scheduled_item(self, snap: CampaignSnapshot) -> WorkItem | None:
        scheduled = [wi for wi in snap.work_items.values() if wi.status is WorkItemStatus.scheduled]
        if not scheduled:
            return None
        scheduled.sort(key=lambda wi: (wi.scheduled_seq or 0, wi.work_item_id))
        return scheduled[-1]

    def _fail_stale_running_items(self, run: _Run) -> int:
        """A work item still ``running`` when EXECUTE begins was interrupted mid-run
        (Ctrl-C, crash): no worker is alive for it, so it is recorded as failed — the
        artifacts it produced stay, and the scheduler may pick its branch again."""
        stale = [wi for wi in run.snap.work_items.values() if wi.status is WorkItemStatus.running]
        for wi in sorted(stale, key=lambda w: w.work_item_id):
            run.store.append(
                ev.EventType.worker_failed,
                ev.WorkerFailedPayload(
                    work_item_id=wi.work_item_id,
                    error_category="other",
                    message="interrupted before completion (engine restarted while running)",
                ),
                role=wi.role,
                branch_id=wi.branch_id,
                work_item_id=wi.work_item_id,
                correlation_id=wi.work_item_id,
            )
            run.store.append(
                ev.EventType.budget_consumed,
                ev.BudgetConsumedPayload(scope="work_item", ref=wi.work_item_id, steps=1),
                role=wi.role,
                branch_id=wi.branch_id,
                work_item_id=wi.work_item_id,
                correlation_id=wi.work_item_id,
            )
        return len(stale)

    def _phase_execute(self, run: _Run) -> PhaseOutcome:
        """Run the scheduled work item through its worker and record what happened."""
        stale = self._fail_stale_running_items(run)
        snap = run.snap
        item = self._scheduled_item(snap)
        if item is None and stale:
            return PhaseOutcome(CampaignPhase.CRITIQUE, f"{stale} interrupted work item(s) failed")
        if item is None:
            return PhaseOutcome(CampaignPhase.CRITIQUE, "no scheduled work item")
        branch = snap.branches.get(item.branch_id)
        if branch is None:
            self._fail(run, f"work item {item.work_item_id} names unknown branch {item.branch_id}")
            return PhaseOutcome(None)
        # Campaign-wide governance caps, consulted from the usage ledger once per work
        # item (every session the campaign ran counts).
        if not self._governance_ok(run):
            return PhaseOutcome(None)
        worker = self.workers.get(item.role)
        budget = item.budget or WorkBudget(max_steps=1)
        ctx = self._worker_context(run, branch=branch, item=item, budget=budget)
        run.store.append(
            ev.EventType.worker_started,
            ev.WorkerStartedPayload(
                work_item_id=item.work_item_id,
                role=item.role,
                session_id=ctx.session_id,
                budget=budget,
            ),
            role=item.role,
            branch_id=branch.branch_id,
            work_item_id=item.work_item_id,
            correlation_id=item.work_item_id,
        )
        exec_ctx = _ExecuteContext(item=item, branch=branch, ctx=ctx)
        if worker is None:
            exec_ctx.result = WorkerResult(
                status="failed",
                error_category="tool_unavailable",
                message=f"no worker registered for role {item.role.value} in this version",
                usage=CostTotals(steps=1),
            )
        else:
            self._run_worker(run, worker, exec_ctx)
        self._record_result(run, exec_ctx)
        return PhaseOutcome(
            CampaignPhase.CRITIQUE, f"{item.work_item_id}: {exec_ctx.result.status}"
        )

    def _governance_ok(self, run: _Run) -> bool:
        from opentorus.governance import BudgetExceeded, assert_within_budget

        try:
            assert_within_budget(self.ot_dir, self.config, campaign_id=run.cid)
        except BudgetExceeded as exc:
            axis = "governance_ledger"
            if axis not in run.snap.budget.exhausted:
                run.store.append(
                    ev.EventType.budget_exhausted,
                    ev.BudgetExhaustedPayload(axis=axis, used=0.0, limit=0.0, scope="campaign"),
                )
            self._pause_now(run, f"{ReasonCode.BUDGET_EXHAUSTED.value}: {exc}")
            return False
        return True

    def _run_worker(self, run: _Run, worker: Worker, ec: _ExecuteContext) -> None:
        rt = self._runtime(run)
        self._collector.reset()
        before = snapshot_artifacts(self.ot_dir, run.pid)
        started = self.clock.now()
        try:
            result = worker.run(ec.ctx, rt)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - a worker bug is a failed item, not a crash
            _logger.warning(
                "worker %s failed on %s: %s", ec.item.role.value, ec.item.work_item_id, exc
            )
            result = WorkerResult(
                status="failed",
                error_category="other",
                message=f"{type(exc).__name__}: {exc}",
                usage=CostTotals(steps=1),
            )
        finished = self.clock.now()
        after = snapshot_artifacts(self.ot_dir, run.pid)
        ec.wall_seconds = round(max(0.0, (finished - started).total_seconds()), 3)
        # Steps: the loop's turns when the worker ran one, else what it declared,
        # never less than the documented one step per work item.
        turns = self._collector.turns
        result.usage = CostTotals(
            steps=max(1, result.usage.steps, turns),
            tokens=max(result.usage.tokens, self._collector.tokens),
            cost_usd=max(result.usage.cost_usd, self._collector.cost_usd),
            work_items=1,
            wall_seconds=ec.wall_seconds,
        )
        ec.result = result
        seen = {r.artifact_id for r in result.artifacts_created}
        derived = [
            r
            for r in diff_artifacts(
                before,
                after,
                branch_id=ec.branch.branch_id,
                work_item_id=ec.item.work_item_id,
                role=ec.item.role,
            )
            if r.artifact_id not in seen
        ]
        ec.new_refs = [*result.artifacts_created, *derived]

    def _record_result(self, run: _Run, ec: _ExecuteContext) -> None:
        item, branch, result = ec.item, ec.branch, ec.result

        def emit(
            event_type: str, payload: BaseModel, *, refs: tuple[str, ...] | list[str] = ()
        ) -> None:
            """Every event of this work item carries the same attribution."""
            run.store.append(
                event_type,
                payload,
                role=item.role,
                branch_id=branch.branch_id,
                work_item_id=item.work_item_id,
                correlation_id=item.work_item_id,
                refs=refs,
            )

        for ref in ec.new_refs:
            emit(
                ev.EventType.artifact_created,
                ref.model_copy(
                    update={
                        "branch_id": ref.branch_id or branch.branch_id,
                        "work_item_id": ref.work_item_id or item.work_item_id,
                        "role": ref.role or item.role,
                    }
                ),
                refs=[ref.artifact_id],
            )
        artifact_ids = [r.artifact_id for r in ec.new_refs]
        if result.status == "failed":
            sig_id: str | None = None
            if result.failure_signature is not None:
                sig = result.failure_signature
                if not sig.signature_id:
                    sig = sig.model_copy(
                        update={
                            "signature_id": ids.mint(
                                run.snap.counters, ids.FAILURE_SIGNATURE_PREFIX
                            )
                        }
                    )
                sig = sig.model_copy(
                    update={"branch_id": branch.branch_id, "work_item_id": item.work_item_id}
                )
                emit(ev.EventType.failure_signature_recorded, sig)
                sig_id = sig.signature_id
            emit(
                ev.EventType.worker_failed,
                ev.WorkerFailedPayload(
                    work_item_id=item.work_item_id,
                    error_category=result.error_category or "other",
                    message=result.message or "; ".join(result.notes),
                    failure_signature_id=sig_id,
                ),
            )
            if result.error_category == "tool_unavailable" and self.workers.get(item.role) is None:
                run.store.append(
                    ev.EventType.branch_exhausted,
                    ev.BranchTerminalPayload(
                        branch_id=branch.branch_id, reason="no worker for the branch's role"
                    ),
                    branch_id=branch.branch_id,
                )
        else:
            emit(
                ev.EventType.worker_completed,
                ev.WorkerCompletedPayload(
                    work_item_id=item.work_item_id,
                    status=result.status,
                    usage=result.usage,
                    artifact_ids=artifact_ids,
                    notes=list(result.notes),
                ),
            )
        emit(
            ev.EventType.budget_consumed,
            ev.BudgetConsumedPayload(
                scope="work_item",
                ref=item.work_item_id,
                steps=result.usage.steps,
                tokens=result.usage.tokens,
                cost_usd=result.usage.cost_usd,
                wall_seconds=ec.wall_seconds,
            ),
        )
        if result.routing_decision_id:
            decision = self.pool.decision(result.routing_decision_id) if self._pool else None
            emit(
                ev.EventType.routing_decision_recorded,
                RouteSummary(
                    decision_id=result.routing_decision_id,
                    task_class=decision.task_class if decision else item.task_class,
                    selected_profile=decision.selected_profile if decision else None,
                    provider=decision.provider if decision else None,
                    actual_model=decision.actual_model if decision else None,
                ),
            )
        if result.coverage_ref:
            emit(
                ev.EventType.coverage_assessed,
                ev.CoverageAssessedPayload(
                    coverage_ref=result.coverage_ref,
                    insufficient=list(result.insufficient_categories),
                    critical=run.profile.critical_coverage,
                ),
                refs=[result.coverage_ref],
            )
        for proposal in result.obligations:
            oid = ids.mint(run.snap.counters, ids.OBLIGATION_PREFIX)
            emit(
                ev.EventType.obligation_created,
                Obligation(
                    obligation_id=oid,
                    campaign_id=run.cid,
                    branch_id=branch.branch_id,
                    statement=proposal.statement,
                    assumptions=list(proposal.assumptions),
                    quantifiers=list(proposal.quantifiers),
                    root_relation=proposal.root_relation,
                    dependencies=list(proposal.dependencies),
                    closure_modes=list(proposal.closure_modes),
                    supporting_artifacts=list(proposal.supporting_artifacts),
                    source_proof_id=proposal.source_proof_id,
                    gap_marker=proposal.gap_marker,
                ),
            )
        if result.status == "branch_done":
            run.store.append(
                ev.EventType.branch_completed,
                ev.BranchTerminalPayload(
                    branch_id=branch.branch_id,
                    reason=f"worker reported branch_done on {item.work_item_id}",
                ),
                branch_id=branch.branch_id,
            )
            run.store.write_branch_card(run.snap.branches[branch.branch_id])

    def _phase_critique(self, run: _Run) -> PhaseOutcome:
        """Adversarial critique of new claims — the M4 critic worker slots in here."""
        return PhaseOutcome(CampaignPhase.VERIFY, "no critic worker in this version")

    def _phase_verify(self, run: _Run) -> PhaseOutcome:
        """Close obligations only when the verifier-coordinator finds a backing artifact."""
        snap = run.snap
        open_obs = [
            o
            for o in snap.obligations.values()
            if o.status in (ObligationStatus.open, ObligationStatus.in_progress)
        ]
        if not open_obs:
            return PhaseOutcome(CampaignPhase.UPDATE_GRAPH, "no open obligations")
        worker = self.workers.get(WorkerRole.verifier_coordinator)
        if worker is None:
            return PhaseOutcome(CampaignPhase.UPDATE_GRAPH, "no verifier-coordinator registered")
        ctx = self._worker_context(run, role=WorkerRole.verifier_coordinator, obligations=open_obs)
        result = worker.run(ctx, self._runtime(run))
        closed = 0
        for proposal in result.closure_proposals:
            ob = run.snap.obligations.get(proposal.obligation_id)
            if ob is None or ob.status is ObligationStatus.closed:
                continue
            run.store.append(
                ev.EventType.obligation_closed,
                ev.ObligationClosedPayload(
                    obligation_id=proposal.obligation_id,
                    artifact_id=proposal.artifact_id,
                    closure_mode=proposal.mode,
                    check_id=proposal.check_id,
                    verdict=proposal.verdict,
                ),
                role=WorkerRole.verifier_coordinator,
                branch_id=ob.branch_id,
                refs=[proposal.artifact_id],
            )
            closed += 1
        return PhaseOutcome(
            CampaignPhase.UPDATE_GRAPH,
            f"{closed} of {len(open_obs)} open obligation(s) closed by accepted artifacts",
        )

    def _phase_update_graph(self, run: _Run) -> PhaseOutcome:
        """Mirror new artifact refs and obligations as campaign proof-tree nodes."""
        snap = run.snap
        by_artifact = {n.artifact_id: n for n in snap.campaign_nodes.values() if n.artifact_id}
        by_obligation = {
            n.obligation_id: n for n in snap.campaign_nodes.values() if n.obligation_id
        }
        created = updated = 0
        for ref in snap.artifact_refs:
            if ref.artifact_id in by_artifact:
                continue
            branch = snap.branches.get(ref.branch_id or "")
            node = CampaignNodeState(
                node_id=ids.mint(run.snap.counters, ids.NODE_PREFIX),
                kind=ref.kind,
                title=f"{ref.kind} {ref.artifact_id}",
                artifact_id=ref.artifact_id,
                branch_id=ref.branch_id,
                work_item_id=ref.work_item_id,
                root_relation=branch.root_relation if branch else RootRelation.unknown,
                status="recorded",
            )
            run.store.append(
                ev.EventType.proof_node_created,
                node,
                branch_id=ref.branch_id,
                refs=[ref.artifact_id],
            )
            created += 1
        for oid in sorted(snap.obligations):
            ob = snap.obligations[oid]
            existing = by_obligation.get(oid)
            if existing is None:
                node = CampaignNodeState(
                    node_id=ids.mint(run.snap.counters, ids.NODE_PREFIX),
                    kind="obligation",
                    title=ob.statement[:80],
                    statement=ob.statement,
                    obligation_id=oid,
                    branch_id=ob.branch_id,
                    root_relation=ob.root_relation,
                    status=ob.status.value,
                )
                run.store.append(
                    ev.EventType.proof_node_created, node, branch_id=ob.branch_id, refs=[oid]
                )
                created += 1
            elif node.status != ob.status.value:
                run.store.append(
                    ev.EventType.proof_node_updated,
                    ev.ProofNodeUpdatedPayload(
                        node_id=node.node_id, changes={"status": ob.status.value}
                    ),
                    branch_id=ob.branch_id,
                    refs=[oid],
                )
                updated += 1
        return PhaseOutcome(
            CampaignPhase.REALLOCATE, f"{created} node(s) created, {updated} updated"
        )

    def _phase_reallocate(self, run: _Run) -> PhaseOutcome:
        """Budget check (pause on a newly spent axis), queue activation, completion check."""
        snap = run.snap
        policy = CampaignBudgetPolicy(run.cfg, snap.budget)
        newly = policy.newly_exhausted()
        if newly:
            for axis in newly:
                run.store.append(
                    ev.EventType.budget_exhausted,
                    ev.BudgetExhaustedPayload(
                        axis=axis.axis, used=axis.used, limit=axis.limit, scope="campaign"
                    ),
                )
            self._pause_now(run, ReasonCode.BUDGET_EXHAUSTED.value)
            return PhaseOutcome(None, "budget exhausted")
        # Activate queued proposals while slots are free (M4 adds suspension/reactivation).
        active = [b for b in snap.branches.values() if b.status is BranchStatus.active]
        queued = sorted(
            (b for b in snap.branches.values() if b.status is BranchStatus.proposed),
            key=lambda b: (-b.priority, b.branch_id),
        )
        slot = len(active)
        for branch in queued:
            if slot >= run.cfg.max_active_branches:
                break
            slot += 1
            run.store.append(
                ev.EventType.branch_activated,
                ev.BranchActivatedPayload(
                    branch_id=branch.branch_id, priority=branch.priority, slot=slot
                ),
                branch_id=branch.branch_id,
            )
        facts = gather_dossier_facts(self.ot_dir, run.pid, run.snap)
        verdict = run.profile.completion(run.snap, facts)
        if verdict.complete:
            return PhaseOutcome(CampaignPhase.SYNTHESIZE, verdict.reason)
        return PhaseOutcome(CampaignPhase.SCHEDULE, verdict.reason)

    def _phase_synthesize(self, run: _Run) -> PhaseOutcome:
        """Write progress + rebuild the report, then complete with the mode's criterion."""
        notes: list[str] = []
        worker = self.workers.get(WorkerRole.synthesizer)
        if worker is not None:
            ctx = self._worker_context(run, role=WorkerRole.synthesizer)
            try:
                result = worker.run(ctx, self._runtime(run))
                notes.extend(result.notes)
            except Exception as exc:  # noqa: BLE001 - synthesis must not block completion
                notes.append(f"synthesizer failed: {exc}")
        facts = gather_dossier_facts(self.ot_dir, run.pid, run.snap)
        verdict = run.profile.completion(run.snap, facts)
        reason = verdict.reason if verdict.complete else "no schedulable work item remained"
        criterion = verdict.criterion if verdict.complete else "no_work"
        run.store.append(
            ev.EventType.campaign_completed,
            ev.CampaignCompletedPayload(
                reason=f"{reason}; problem status per dossier: {facts.root_label}",
                mode_criterion=criterion,
            ),
        )
        _logger.info("campaign %s completed: %s (%s)", run.cid, reason, "; ".join(notes))
        return PhaseOutcome(None, reason)

    # -- worker context -----------------------------------------------------------------

    def _shared_artifacts(self, run: _Run) -> tuple[ArtifactRef, ...]:
        """Only verified/accepted artifacts are shared with workers."""
        from opentorus.research.dossier import store as dstore
        from opentorus.research.epistemics import is_verification_evidence
        from opentorus.research.theorems import store as thm_store
        from opentorus.research.verifiers.proofs import get_proof

        out: list[ArtifactRef] = []
        for ref in run.snap.artifact_refs:
            if ref.kind == "proof":
                proof = get_proof(self.ot_dir, ref.artifact_id)
                if proof is not None and proof.accepted and not proof.inconclusive:
                    out.append(ref)
            elif ref.kind == "theorem_reference":
                thm = thm_store.get_reference(self.ot_dir, ref.artifact_id)
                if thm is not None and thm.review_status == "accepted":
                    out.append(ref)
            elif ref.kind == "evidence":
                for evd in dstore.list_evidence(self.ot_dir, run.pid):
                    if evd.id == ref.artifact_id and is_verification_evidence(evd.type):
                        out.append(ref)
                        break
            elif ref.kind == "coverage":
                out.append(ref)
        return tuple(out)

    def _worker_context(
        self,
        run: _Run,
        *,
        role: WorkerRole | None = None,
        branch: BranchRecord | None = None,
        item: WorkItem | None = None,
        budget: WorkBudget | None = None,
        obligations: list[Obligation] | None = None,
    ) -> WorkerContext:
        snap = run.snap
        role = role or (item.role if item is not None else WorkerRole.strategist)
        problem = snap.normalized_problem or NormalizedProblem(problem_id=run.pid, statement="")
        session = (
            item.session_id
            if item is not None and item.session_id
            else f"{run.cid}:{branch.branch_id if branch else 'campaign'}:{role.value}"
        )
        task_class = (
            item.task_class
            if item is not None
            else ROLE_TASK_CLASS.get(role, TaskClass.default).value
        )
        return WorkerContext(
            campaign_id=run.cid,
            branch_id=branch.branch_id if branch else None,
            work_item_id=item.work_item_id if item else None,
            role=role,
            task_class=task_class,
            mode=run.record.mode,
            root_problem=problem,
            branch_objective=branch.objective if branch else "",
            strategy_summary=branch.strategy_summary if branch else "",
            root_relation=branch.root_relation if branch else RootRelation.unknown,
            assumption_context=tuple(branch.assumption_context) if branch else (),
            shared_artifacts=self._shared_artifacts(run),
            theorem_refs=tuple(
                r.artifact_id for r in snap.artifact_refs if r.kind == "theorem_reference"
            ),
            failure_signatures=tuple(
                snap.failure_signatures[s]
                for s in (branch.failure_signatures if branch else [])
                if s in snap.failure_signatures
            ),
            open_obligations=tuple(
                obligations
                if obligations is not None
                else [
                    o
                    for o in snap.obligations.values()
                    if o.status is ObligationStatus.open
                    and (branch is None or o.branch_id == branch.branch_id)
                ]
            ),
            budget=budget or WorkBudget(max_steps=1),
            session_id=session,
            coverage_ref=snap.coverage_ref,
            insufficient_categories=tuple(snap.insufficient_categories),
        )


__all__ = [
    "PRIMARY_CLAIM_REMEDIATION",
    "CampaignConfigError",
    "CampaignEngine",
    "PhaseOutcome",
    "ResumeResult",
]
