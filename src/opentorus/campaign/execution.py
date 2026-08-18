"""Running one work item and turning what the worker did into events.

Split out of :mod:`opentorus.campaign.engine`: the engine decides *which* work item
runs (phases); :class:`WorkerExecutor` runs it and records the outcome. The contract
the rest of the layer relies on:

* a worker sees only a frozen :class:`WorkerContext` built by
  :meth:`WorkerExecutor.worker_context` — ids, *verified/accepted* shared artifacts,
  its own branch's artifact ids, its budget, its allowed tools, its own session id;
  never a transcript, never another branch's session;
* the artifacts a run produced are the union of what the worker declared and what
  changed in the dossier/workspace ledgers between the before/after snapshots
  (:func:`diff_artifacts`), so a worker cannot leave an artifact unrecorded;
* every event of a work item carries the same attribution (role, branch, work item,
  correlation id) and the order is fixed: artifacts → target claim → verifications →
  failure signature / completion → budget → routing → coverage → obligations →
  reviews → branch terminal; nothing here sets a claim status;
* a failure signature that repeats an already recorded key reuses that signature's
  id (the reducer bumps ``occurrences``); a new key mints ``FSIG-`` from the counter;
* steps charged = the loop's model turns when the worker ran one, else what it
  declared, never less than the documented one step per work item.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from opentorus.agent.control.events import RunEvent, RunEventSink, TurnCompleted
from opentorus.campaign import events as ev
from opentorus.campaign import ids
from opentorus.campaign.budget import CampaignBudgetPolicy
from opentorus.campaign.clock import Clock
from opentorus.campaign.failures import find_signature, signature_key
from opentorus.campaign.lifecycle import RunContext
from opentorus.campaign.models import (
    ArtifactRef,
    BranchRecord,
    CostTotals,
    NormalizedProblem,
    Obligation,
    ObligationStatus,
    RootRelation,
    RouteSummary,
    VerificationRef,
    WorkBudget,
    WorkerContext,
    WorkerResult,
    WorkerRole,
    WorkItem,
    WorkItemStatus,
)
from opentorus.campaign.scheduler import ROLE_TASK_CLASS
from opentorus.campaign.workers import Worker, WorkerRuntime
from opentorus.campaign.workers.base import (
    ROLE_ALLOWED_TOOLS,
    RegistryFactory,
    diff_artifacts,
    snapshot_artifacts,
)
from opentorus.config import Config
from opentorus.providers.pool import ProviderPool, TaskClass

_logger = logging.getLogger("opentorus")

# Kinds whose ``artifact_created`` should be followed by a verification request: the
# workspace ``PROOF-*`` ledger already carries a backend verdict (recorded too).
_LEDGER_PROOF_KIND = "proof"


class UsageCollector:
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
class ExecuteContext:
    """The per-work-item facts the executor carries while a worker runs."""

    item: WorkItem
    branch: BranchRecord
    ctx: WorkerContext
    result: WorkerResult = field(default_factory=WorkerResult)
    new_refs: list[ArtifactRef] = field(default_factory=list)
    wall_seconds: float = 0.0


class WorkerExecutor:
    """Runs workers for an engine and records their results as events."""

    def __init__(
        self,
        *,
        root: Path,
        ot_dir: Path,
        config: Config,
        clock: Clock,
        pool: Callable[[], ProviderPool],
        workers: dict[WorkerRole, Worker],
        collector: UsageCollector,
        confirm: object | None = None,
        registry_factory: RegistryFactory | None = None,
        stop_flag: Callable[[], bool] | None = None,
    ) -> None:
        self.root = root
        self.ot_dir = ot_dir
        self.config = config
        self.clock = clock
        self._pool = pool
        self.workers = workers
        self.collector = collector
        self._confirm = confirm
        self._registry_factory = registry_factory
        self._stop_flag = stop_flag

    # -- services -------------------------------------------------------------------

    def runtime(self, run: RunContext) -> WorkerRuntime:
        cfg = run.cfg

        def _should_stop() -> bool:
            if self._stop_flag is not None and self._stop_flag():
                return True
            return CampaignBudgetPolicy(cfg, run.snap.budget).is_exhausted()

        return WorkerRuntime(
            root=self.root,
            ot_dir=self.ot_dir,
            config=self.config,
            pool=self._pool(),
            clock=self.clock,
            event_sink=self.collector,
            confirm=self._confirm,  # type: ignore[arg-type]
            registry_factory=self._registry_factory,
            should_stop=_should_stop,
        )

    # -- worker context -------------------------------------------------------------

    def shared_artifacts(self, run: RunContext) -> tuple[ArtifactRef, ...]:
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

    def worker_context(
        self,
        run: RunContext,
        *,
        role: WorkerRole | None = None,
        branch: BranchRecord | None = None,
        item: WorkItem | None = None,
        budget: WorkBudget | None = None,
        obligations: list[Obligation] | None = None,
        review_targets: tuple[str, ...] = (),
    ) -> WorkerContext:
        snap = run.snap
        if role is None:
            if item is not None:
                role = item.role
            elif branch is not None:
                role = branch.assigned_worker_role
            else:
                role = WorkerRole.strategist
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
            shared_artifacts=self.shared_artifacts(run),
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
            allowed_tools=ROLE_ALLOWED_TOOLS.get(role, frozenset()),
            session_id=session,
            coverage_ref=snap.coverage_ref,
            insufficient_categories=tuple(snap.insufficient_categories),
            branch_artifact_ids=tuple(branch.artifact_references) if branch else (),
            target_claim_id=branch.target_claim_id if branch else None,
            review_targets=tuple(review_targets),
            strategy_key=branch.strategy_key if branch else None,
        )

    # -- stale items ------------------------------------------------------------------

    def fail_stale_running_items(self, run: RunContext) -> int:
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

    # -- run ------------------------------------------------------------------------------

    def run_worker(self, run: RunContext, worker: Worker, ec: ExecuteContext) -> None:
        rt = self.runtime(run)
        self.collector.reset()
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
        turns = self.collector.turns
        result.usage = CostTotals(
            steps=max(1, result.usage.steps, turns),
            tokens=max(result.usage.tokens, self.collector.tokens),
            cost_usd=max(result.usage.cost_usd, self.collector.cost_usd),
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

    # -- record ---------------------------------------------------------------------------

    def record_result(self, run: RunContext, ec: ExecuteContext) -> None:
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
        if result.target_claim_id and result.target_claim_id != branch.target_claim_id:
            emit(
                ev.EventType.branch_updated,
                ev.BranchUpdatedPayload(
                    branch_id=branch.branch_id, changes={"target_claim_id": result.target_claim_id}
                ),
                refs=[result.target_claim_id],
            )
        self._record_verifications(emit, ec)
        if result.status == "failed":
            sig_id: str | None = None
            if result.failure_signature is not None:
                sig = result.failure_signature
                key = sig.key or signature_key(sig)
                prior = find_signature(run.snap, key)
                sig = sig.model_copy(
                    update={
                        "key": key,
                        "signature_id": (
                            prior.signature_id
                            if prior is not None
                            else ids.mint(run.snap.counters, ids.FAILURE_SIGNATURE_PREFIX)
                        ),
                        "branch_id": branch.branch_id,
                        "work_item_id": item.work_item_id,
                    }
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
            decision = self._pool().decision(result.routing_decision_id)
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
            if proposal.gap_marker is None and proposal.source_proof_id:
                # A whole-proof obligation: the attempt is gap-free and could be checked.
                emit(
                    ev.EventType.verification_requested,
                    ev.VerificationRequestedPayload(
                        artifact_id=proposal.source_proof_id, backend="referee"
                    ),
                    refs=[proposal.source_proof_id],
                )
        for review in result.reviews:
            emit(ev.EventType.review_recorded, review, refs=[review.review_id])
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

    def _record_verifications(self, emit: Callable[..., None], ec: ExecuteContext) -> None:
        """``verification_requested`` + ``verification_recorded`` for every workspace
        ``PROOF-*`` this work item produced (the ledger already holds the backend's
        verdict), using the worker's own refs when it reported them."""
        from opentorus.research.verifiers.proofs import get_proof

        reported = {v.artifact_id: v for v in ec.result.verifications}
        done: set[str] = set()
        for ref in ec.new_refs:
            if ref.kind != _LEDGER_PROOF_KIND or ref.artifact_id in done:
                continue
            done.add(ref.artifact_id)
            vref = reported.get(ref.artifact_id)
            if vref is None:
                proof = get_proof(self.ot_dir, ref.artifact_id)
                if proof is None:
                    continue
                vref = VerificationRef(
                    artifact_id=proof.id,
                    backend=proof.backend,
                    accepted=bool(proof.accepted),
                    inconclusive=bool(proof.inconclusive),
                )
            emit(
                ev.EventType.verification_requested,
                ev.VerificationRequestedPayload(artifact_id=vref.artifact_id, backend=vref.backend),
                refs=[vref.artifact_id],
            )
            emit(ev.EventType.verification_recorded, vref, refs=[vref.artifact_id])
        for aid, vref in sorted(reported.items()):
            if aid in done:
                continue
            emit(
                ev.EventType.verification_requested,
                ev.VerificationRequestedPayload(artifact_id=aid, backend=vref.backend),
                refs=[aid],
            )
            emit(ev.EventType.verification_recorded, vref, refs=[aid])


__all__ = ["ExecuteContext", "UsageCollector", "WorkerExecutor"]
