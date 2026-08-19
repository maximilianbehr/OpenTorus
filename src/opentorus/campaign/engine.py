"""The campaign engine: a thin phase orchestrator over the store and the workers.

One named method per working phase (``_phase_ingest`` … ``_phase_synthesize``),
each doing exactly its phase's work through store events and returning the next
phase; :meth:`CampaignEngine.run` is the loop that walks the table. The engine
never crashes the CLI on a bad transition — the store refuses it and the engine
records ``campaign_failed`` — and it never touches a claim status: everything it
learns about the problem it learns by reading dossier artifacts.

Lifecycle: :meth:`start` validates the request (mode, branches, budgets, the
prove-or-refute primary-claim rule D10 — see :mod:`lifecycle`), allocates a
workspace-unique id, creates the store and runs; :meth:`resume` is idempotent on
terminal campaigns; :meth:`pause` / :meth:`stop` record their reasons;
``KeyboardInterrupt`` pauses with reason ``interrupted`` and re-raises so the CLI can
exit 130. Worker execution and result recording live in :mod:`execution`.

The round: SCHEDULE picks the best-scored runnable branch (:mod:`scheduler`) but
refuses to re-run a recorded failure unchanged (:mod:`failures` — ``retry_refused``
then ``branch_suspended``); EXECUTE runs the worker; CRITIQUE reviews the round's new
claims/proofs; VERIFY closes obligations only through the verifier-coordinator's
proposals; UPDATE_GRAPH mirrors artifacts as nodes; REALLOCATE pauses on a spent
budget, suspends branches on repeated identical failures, exhausts branches out of
step budget, reactivates suspended branches only when a recorded condition is met,
activates queued branches, and asks the mode's completion criterion.

Determinism: ids are minted from the snapshot's counters, timestamps from the
injected clock, and the mock/offline path performs no network I/O, so two fresh
workspaces produce identical event sequences.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path

from opentorus.agent.control.events import RunEventSink
from opentorus.agent.control.models import ReasonCode
from opentorus.agent.control.phase_machine import InvalidTransition
from opentorus.campaign import events as ev
from opentorus.campaign import ids
from opentorus.campaign.budget import CampaignBudgetPolicy
from opentorus.campaign.clock import Clock, SystemClock
from opentorus.campaign.execution import ExecuteContext, UsageCollector, WorkerExecutor
from opentorus.campaign.facts import gather_dossier_facts
from opentorus.campaign.lifecycle import (
    PRIMARY_CLAIM_REMEDIATION,
    CampaignConfigError,
    PhaseOutcome,
    ResumeResult,
    RunContext,
    create_campaign,
    normalize_problem,
)
from opentorus.campaign.models import (
    ArtifactRef,
    BranchStatus,
    CampaignMode,
    CampaignPhase,
    CampaignRecord,
    CampaignSnapshot,
    CampaignStatus,
    CostTotals,
    NormalizedProblem,
    ObligationStatus,
    WorkBudget,
    WorkerResult,
    WorkerRole,
    WorkItem,
    WorkItemStatus,
)
from opentorus.campaign.phases import DossierFacts, is_terminal, mode_profile
from opentorus.campaign.portfolio import PortfolioContext, generate_portfolio
from opentorus.campaign.progress import write_progress
from opentorus.campaign.reallocation import (
    activate_queued,
    critique_targets,
    reactivate,
    retry_gate,
    suspend_and_exhaust,
)
from opentorus.campaign.recording import mirror_graph, record_closures, record_portfolio
from opentorus.campaign.scheduler import select_next
from opentorus.campaign.status import summarize_snapshot
from opentorus.campaign.store import open_campaign
from opentorus.campaign.workers import DEFAULT_WORKERS, Worker
from opentorus.campaign.workers.base import RegistryFactory
from opentorus.config import Config
from opentorus.errors import OpenTorusError
from opentorus.providers.pool import ProviderPool

_logger = logging.getLogger("opentorus")


PROVIDER_OUTAGE_STREAK = 3


def provider_outage(snap: CampaignSnapshot) -> str | None:
    """The message of the last failure when the ``PROVIDER_OUTAGE_STREAK`` most recent
    finished work items all failed with ``provider_unavailable``; else ``None``.

    Only work items that reached a worker count (scheduled-but-refused retries do not
    finish), any success or differently-failed item breaks the streak, and only items
    created after the last resume count — otherwise a resumed campaign re-paused on the
    very failures that paused it, without trying the endpoint again (observed live).
    """
    since = int(snap.counters.get("last_resume_seq", 0))
    finished = [
        wi
        for wi in sorted(snap.work_items.values(), key=lambda w: w.created_seq)
        if wi.status.value in ("completed", "failed") and wi.created_seq > since
    ]
    tail = finished[-PROVIDER_OUTAGE_STREAK:]
    if len(tail) < PROVIDER_OUTAGE_STREAK:
        return None

    def _provider_failure(wi: WorkItem) -> bool:
        if wi.status.value != "failed":
            return False
        sig = snap.failure_signatures.get(wi.failure_signature_id or "")
        if sig is not None:
            return sig.error_category == "provider_unavailable"
        return (wi.failure_reason or "").startswith(("ProviderError", "ConnectionError"))

    if all(_provider_failure(wi) for wi in tail):
        return tail[-1].failure_reason or "provider unavailable"
    return None


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
        self._collector = UsageCollector(event_sink)
        self._executor = WorkerExecutor(
            root=root,
            ot_dir=ot_dir,
            config=config,
            clock=self.clock,
            pool=lambda: self.pool,
            workers=self.workers,
            collector=self._collector,
            confirm=confirm,
            registry_factory=registry_factory,
            stop_flag=stop_flag,
        )
        self._handlers: dict[CampaignPhase, Callable[[RunContext], PhaseOutcome]] = {
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

    def _open(self, campaign_id: str) -> RunContext:
        store = open_campaign(self.ot_dir, campaign_id, clock=self.clock)
        loaded = store.load()
        return RunContext(
            store=store, record=loaded.record, profile=mode_profile(loaded.record.mode)
        )

    def _facts(self, run: RunContext) -> DossierFacts:
        return gather_dossier_facts(self.ot_dir, run.pid, run.snap, config=self.config)

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
        run_ctx = create_campaign(
            self.ot_dir,
            self.config,
            self.clock,
            problem_id=problem_id,
            mode=mode,
            branches=branches,
            max_steps=max_steps,
            token_budget=token_budget,
            max_wall_seconds=max_wall_seconds,
            cost_budget=cost_budget,
            designate_primary_claim=create_primary_claim,
            notice=self._notice,
        )
        record = run_ctx.record
        self._write_progress(run_ctx)
        if run:
            self.run(record.id)
        return record

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
        except Exception as exc:  # noqa: BLE001 — a crash must not leave the campaign 'running'
            # A worker, provider or dossier operation blew up mid-phase. The log is
            # already consistent (events are written before the snapshot), so the honest
            # move is a recorded pause naming the error: the campaign stays inspectable
            # and resumable instead of sitting on disk as 'running' with no trace of why
            # it stopped. The exception still propagates so the CLI reports it.
            self._pause_now(run, f"error: {type(exc).__name__}: {exc}"[:500])
            try:
                self._write_progress(run)
            except Exception:  # noqa: BLE001 — progress.md is a courtesy, never the record
                _logger.debug("could not write progress for %s after an error", run.cid)
            raise
        self._write_progress(run)
        return run.snap

    def _loop(self, run: RunContext, until: Callable[[CampaignSnapshot], bool] | None) -> None:
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

    def _advance(self, run: RunContext, outcome: str, next_phase: CampaignPhase) -> None:
        current = run.snap.phase
        run.store.append(
            ev.EventType.phase_completed,
            ev.PhaseCompletedPayload(phase=current, outcome=outcome, next_phase=next_phase),
        )
        run.store.append(
            ev.EventType.phase_entered,
            ev.PhaseEnteredPayload(phase=next_phase, from_phase=current, reason=outcome),
        )

    def _pause_now(self, run: RunContext, reason: str) -> None:
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

    def _fail(self, run: RunContext, reason: str) -> None:
        snap = run.snap
        if is_terminal(snap.phase):
            return
        try:
            run.store.append(ev.EventType.campaign_failed, ev.CampaignFailedPayload(reason=reason))
        except OpenTorusError:
            _logger.warning("could not record failure of %s: %s", run.cid, reason)

    def _write_progress(self, run: RunContext) -> None:
        try:
            events, _diags = run.store.read_events()
            summary = summarize_snapshot(self.ot_dir, run.snap, events=events)
            write_progress(run.store, summary)
        except (OpenTorusError, OSError) as exc:  # progress is a courtesy, never a blocker
            _logger.warning("could not write progress for %s: %s", run.cid, exc)

    # -- phases -----------------------------------------------------------------------

    def _phase_ingest(self, run: RunContext) -> PhaseOutcome:
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

    def _phase_normalize(self, run: RunContext) -> PhaseOutcome:
        """Build the NormalizedProblem every worker sees, from dossier facts only."""
        normalized = normalize_problem(self.ot_dir, run.pid)
        run.store.append(ev.EventType.problem_normalized, normalized)
        return PhaseOutcome(
            CampaignPhase.MAP_LITERATURE,
            f"target scope {normalized.target_scope}; {len(normalized.assumptions)} assumption(s), "
            f"{len(normalized.definitions)} definition(s)",
        )

    def _phase_map_literature(self, run: RunContext) -> PhaseOutcome:
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

    def _phase_generate_portfolio(self, run: RunContext) -> PhaseOutcome:
        """Propose, de-duplicate, cap and activate branches; one Approach per accepted one."""

        snap = run.snap
        problem = snap.normalized_problem or NormalizedProblem(problem_id=run.pid, statement="")
        pctx = PortfolioContext(
            campaign_id=run.cid,
            mode=run.record.mode,
            problem=problem,
            coverage_insufficient=tuple(snap.insufficient_categories),
            critical_categories=tuple(run.profile.critical_coverage),
            initial_branches=run.cfg.initial_branches,
            max_active_branches=run.cfg.max_active_branches,
            branch_counter=int(snap.counters.get(ids.BRANCH_PREFIX, 0)),
            existing_branches=tuple(snap.branches.values()),
        )
        self._collector.reset()
        proposal = generate_portfolio(self._executor.runtime(run), pctx)
        if self._collector.turns:
            run.store.append(
                ev.EventType.budget_consumed,
                ev.BudgetConsumedPayload(
                    scope="model_invocation",
                    ref="strategist",
                    steps=self._collector.turns,
                    tokens=self._collector.tokens,
                    cost_usd=self._collector.cost_usd,
                ),
                role=WorkerRole.strategist,
            )
        record_portfolio(run, proposal, self.ot_dir)
        active = sum(1 for b in run.snap.branches.values() if b.status is BranchStatus.active)
        outcome = (
            f"{len(proposal.proposals)} proposal(s) ({proposal.source}), "
            f"{len(proposal.accepted)} accepted, {len(proposal.rejected)} rejected, "
            f"{active} active"
        )
        if proposal.notes:
            outcome += "; " + "; ".join(proposal.notes)
        return PhaseOutcome(CampaignPhase.SCHEDULE, outcome)

    def _phase_schedule(self, run: RunContext) -> PhaseOutcome:
        """Pick the next work item — refusing an unchanged repeat of a recorded failure —
        or hand over to synthesis when nothing is runnable."""
        facts = self._facts(run)
        excluded: set[str] = set()
        refused = 0
        while True:
            snap = run.snap
            plan = select_next(
                snap,
                run.cfg.scheduler_weights,
                run.record.mode,
                facts,
                branch_step_budget=run.cfg.branch_step_budget,
                exclude=frozenset(excluded),
            )
            if plan is None:
                if activate_queued(run):
                    continue
                note = f"; {refused} retry refused" if refused else ""
                return PhaseOutcome(CampaignPhase.SYNTHESIZE, f"no runnable work item{note}")
            if not retry_gate(run, plan, facts, self.config):
                refused += 1
                excluded.add(plan.branch_id)
                continue
            break
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

    def _phase_execute(self, run: RunContext) -> PhaseOutcome:
        """Run the scheduled work item through its worker and record what happened."""
        stale = self._executor.fail_stale_running_items(run)
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
        ctx = self._executor.worker_context(run, branch=branch, item=item, budget=budget)
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
        exec_ctx = ExecuteContext(item=item, branch=branch, ctx=ctx)
        if worker is None:
            exec_ctx.result = WorkerResult(
                status="failed",
                error_category="tool_unavailable",
                message=f"no worker registered for role {item.role.value} in this version",
                usage=CostTotals(steps=1),
            )
        else:
            self._executor.run_worker(run, worker, exec_ctx)
        self._executor.record_result(run, exec_ctx)
        return PhaseOutcome(
            CampaignPhase.CRITIQUE, f"{item.work_item_id}: {exec_ctx.result.status}"
        )

    def _governance_ok(self, run: RunContext) -> bool:
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

    def _phase_critique(self, run: RunContext) -> PhaseOutcome:
        """Adversarial review of the round's new claims / proof attempts (the critic)."""
        targets = critique_targets(run.snap)
        if not targets:
            return PhaseOutcome(CampaignPhase.VERIFY, "no new claim or proof attempt to review")
        worker = self.workers.get(WorkerRole.critic)
        if worker is None:
            return PhaseOutcome(CampaignPhase.VERIFY, "no critic registered")
        for target in targets:
            run.store.append(
                ev.EventType.review_requested,
                ev.ReviewRequestedPayload(target_id=target, kind="review"),
                role=WorkerRole.critic,
                refs=[target],
            )
        ctx = self._executor.worker_context(
            run, role=WorkerRole.critic, review_targets=tuple(targets)
        )
        try:
            result = worker.run(ctx, self._executor.runtime(run))
        except Exception as exc:  # noqa: BLE001 - a review failure must not block the round
            return PhaseOutcome(CampaignPhase.VERIFY, f"critic failed: {exc}")
        for review in result.reviews:
            run.store.append(
                ev.EventType.review_recorded,
                review,
                role=WorkerRole.critic,
                refs=[review.review_id, review.target_id],
            )
        return PhaseOutcome(
            CampaignPhase.VERIFY,
            f"{len(result.reviews)} review(s) recorded for {len(targets)} target(s)"
            + ("; " + "; ".join(result.notes[:3]) if result.notes else ""),
        )

    def _phase_verify(self, run: RunContext) -> PhaseOutcome:
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
        ctx = self._executor.worker_context(
            run, role=WorkerRole.verifier_coordinator, obligations=open_obs
        )
        result = worker.run(ctx, self._executor.runtime(run))
        closed = record_closures(run, result.closure_proposals)
        return PhaseOutcome(
            CampaignPhase.UPDATE_GRAPH,
            f"{closed} of {len(open_obs)} open obligation(s) closed by accepted artifacts",
        )

    def _phase_update_graph(self, run: RunContext) -> PhaseOutcome:
        """Mirror new artifact refs and obligations as campaign proof-tree nodes."""
        created, updated = mirror_graph(run)
        return PhaseOutcome(
            CampaignPhase.REALLOCATE, f"{created} node(s) created, {updated} updated"
        )

    def _phase_reallocate(self, run: RunContext) -> PhaseOutcome:
        """Budget check (pause on a newly spent axis), suspension / exhaustion /
        reactivation of branches, queue activation, completion check."""
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
        outage = provider_outage(snap)
        if outage is not None:
            # Three model-driven work items in a row died on the provider/network: the
            # endpoint is gone, not the mathematics. Pause (resumable) instead of letting
            # every branch spend its budget against a dead socket.
            self._pause_now(run, f"PROVIDER_UNAVAILABLE: {outage}"[:500])
            return PhaseOutcome(None, "provider unavailable")
        facts = self._facts(run)
        notes: list[str] = []
        suspended = suspend_and_exhaust(run, facts)
        if suspended:
            notes.append(suspended)
        reactivated = reactivate(run, facts)
        if reactivated:
            notes.append(reactivated)
        activated = activate_queued(run)
        if activated:
            notes.append(f"{activated} queued branch(es) activated")
        verdict = run.profile.completion(run.snap, self._facts(run))
        reason = verdict.reason + ("; " + "; ".join(notes) if notes else "")
        if verdict.complete:
            parked = sorted(
                b.branch_id
                for b in run.snap.branches.values()
                if b.status is BranchStatus.suspended
            )
            if parked:
                # Suspended branches do not keep a campaign alive: they wait for a
                # recorded reactivation condition that only outside work can satisfy.
                reason += (
                    f"; {len(parked)} suspended branch(es) await their reactivation "
                    f"conditions ({', '.join(parked)})"
                )
            return PhaseOutcome(CampaignPhase.SYNTHESIZE, reason)
        return PhaseOutcome(CampaignPhase.SCHEDULE, reason)

    def _phase_synthesize(self, run: RunContext) -> PhaseOutcome:
        """Write progress + rebuild the report, then complete with the mode's criterion."""
        notes: list[str] = []
        worker = self.workers.get(WorkerRole.synthesizer)
        if worker is not None:
            ctx = self._executor.worker_context(run, role=WorkerRole.synthesizer)
            try:
                result = worker.run(ctx, self._executor.runtime(run))
                notes.extend(result.notes)
            except Exception as exc:  # noqa: BLE001 - synthesis must not block completion
                notes.append(f"synthesizer failed: {exc}")
        facts = self._facts(run)
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


__all__ = [
    "PRIMARY_CLAIM_REMEDIATION",
    "CampaignConfigError",
    "CampaignEngine",
    "PhaseOutcome",
    "ResumeResult",
]
