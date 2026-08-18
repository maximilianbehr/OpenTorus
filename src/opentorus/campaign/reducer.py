"""The pure reducer: ``snapshot × event → snapshot``.

Purity is the contract that makes ``snapshot.json`` disposable: no clock (every
timestamp is copied from the event), no ids minted (the engine mints them from the
snapshot's counters *before* appending; the reducer only records them by advancing
the counter to the id it sees), no I/O, no randomness. Replaying the log therefore
reproduces the snapshot exactly — ``campaign verify`` checks that.

Robustness rules (an old or damaged log must still fold):

* unknown event type → ``Diagnostic(kind="unknown_event_type")``, event otherwise ignored;
* known type with an invalid payload → ``Diagnostic(kind="invalid_payload")``, ignored;
* an event that would make an illegal phase transition → ``Diagnostic(kind=
  "invalid_transition")``, skipped (at append time the store refuses it instead);
* a duplicate ``seq`` → ``Diagnostic(kind="seq_duplicate")``, skipped.

Every handler receives a *private deep copy* of the incoming snapshot and mutates
that; :func:`apply` returns it. Callers never see their input change.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import BaseModel, ValidationError

from opentorus.campaign import events as ev
from opentorus.campaign import ids
from opentorus.campaign.models import (
    ArtifactRef,
    BranchRecord,
    BranchStatus,
    BudgetLedger,
    CampaignNodeState,
    CampaignPhase,
    CampaignRecord,
    CampaignSnapshot,
    CampaignStatus,
    CostTotals,
    CurrentWorker,
    Diagnostic,
    FailureSignature,
    NormalizedProblem,
    Obligation,
    ObligationStatus,
    PhaseEntry,
    ReviewRef,
    RouteSummary,
    VerificationRef,
    WorkItem,
    WorkItemStatus,
)
from opentorus.campaign.phases import can_transition

RECENT_EVENTS_KEPT = 20

Handler = Callable[[CampaignSnapshot, ev.CampaignEvent, BaseModel], None]


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _diag(
    snapshot: CampaignSnapshot, kind: str, message: str, event: ev.CampaignEvent | None = None
) -> None:
    snapshot.diagnostics.append(
        Diagnostic(
            kind=kind,  # type: ignore[arg-type]
            message=message,
            seq=event.seq if event is not None else None,
            recorded_at=event.timestamp if event is not None else None,
        )
    )


def _bump_counter(snapshot: CampaignSnapshot, prefix: str, ident: str) -> None:
    """Advance ``counters[prefix]`` to the numeric suffix of ``ident`` (never backwards)."""
    n = ids.numeric_suffix(ident)
    if n is None:
        return
    snapshot.counters[prefix] = max(int(snapshot.counters.get(prefix, 0)), n)


def _enter_phase(
    snapshot: CampaignSnapshot,
    event: ev.CampaignEvent,
    target: CampaignPhase,
    *,
    reason: str = "",
) -> bool:
    """Move to ``target`` if the table allows it; else record a diagnostic and refuse."""
    current = snapshot.phase
    if not can_transition(current, target, resume_phase=snapshot.resume_phase):
        _diag(
            snapshot,
            "invalid_transition",
            f"{event.type} at seq {event.seq}: {current.value} -> {target.value} is not allowed",
            event,
        )
        return False
    snapshot.phase = target
    snapshot.phase_history.append(
        PhaseEntry(
            phase=target,
            from_phase=current,
            entered_seq=event.seq,
            entered_at=event.timestamp,
            reason=reason,
        )
    )
    if target is CampaignPhase.SCHEDULE:
        snapshot.rounds += 1
    return True


def _add_ref(snapshot: CampaignSnapshot, ref: ArtifactRef) -> None:
    for existing in snapshot.artifact_refs:
        if existing.artifact_id == ref.artifact_id and existing.kind == ref.kind:
            return
    snapshot.artifact_refs.append(ref)
    if ref.branch_id and ref.branch_id in snapshot.branches:
        branch = snapshot.branches[ref.branch_id]
        if ref.artifact_id not in branch.artifact_references:
            branch.artifact_references.append(ref.artifact_id)
    if ref.work_item_id and ref.work_item_id in snapshot.work_items:
        wi = snapshot.work_items[ref.work_item_id]
        if ref.artifact_id not in wi.artifact_ids:
            wi.artifact_ids.append(ref.artifact_id)


def _charge(ledger: BudgetLedger, key: str, table: dict[str, CostTotals], p: object) -> None:
    payload = p  # BudgetConsumedPayload
    steps = int(getattr(payload, "steps", 0))
    tokens = int(getattr(payload, "tokens", 0))
    cost = float(getattr(payload, "cost_usd", 0.0))
    wall = float(getattr(payload, "wall_seconds", 0.0))
    table[key] = table.get(key, CostTotals()).plus(
        steps=steps, tokens=tokens, cost_usd=cost, wall_seconds=wall
    )


# --------------------------------------------------------------------------------------
# handlers (one per event type; mutate the private copy)
# --------------------------------------------------------------------------------------


def _apply_campaign_created(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    # The creating event seeded the snapshot in empty_snapshot(); a second one is noise.
    return None


def _apply_campaign_started(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    s.status = CampaignStatus.running
    if s.started_at is None:
        s.started_at = e.timestamp


def _apply_phase_entered(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.PhaseEnteredPayload)
    _enter_phase(s, e, p.phase, reason=p.reason)


def _apply_phase_completed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    return None


def _apply_branch_proposed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, BranchRecord)
    branch = p.model_copy(deep=True)
    if branch.created_at is None:
        branch.created_at = e.timestamp
    branch.updated_at = e.timestamp
    s.branches[branch.branch_id] = branch
    _bump_counter(s, ids.BRANCH_PREFIX, branch.branch_id)


def _branch(s: CampaignSnapshot, e: ev.CampaignEvent, branch_id: str) -> BranchRecord | None:
    branch = s.branches.get(branch_id)
    if branch is None:
        _diag(s, "invalid_payload", f"{e.type} names unknown branch {branch_id}", e)
        return None
    branch.updated_at = e.timestamp
    return branch


def _apply_branch_rejected(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.BranchRejectedPayload)
    branch = _branch(s, e, p.branch_id)
    if branch is None:
        return
    branch.status = BranchStatus.rejected
    branch.rejection_reason = p.reason_code
    branch.duplicate_of = p.duplicate_of
    if p.note:
        branch.distinctness_note = p.note


def _apply_branch_activated(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.BranchActivatedPayload)
    branch = _branch(s, e, p.branch_id)
    if branch is None:
        return
    branch.status = BranchStatus.active
    branch.priority = p.priority


def _apply_branch_suspended(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.BranchSuspendedPayload)
    branch = _branch(s, e, p.branch_id)
    if branch is None:
        return
    branch.status = BranchStatus.suspended
    branch.suspension_reason = p.reason_code
    branch.reactivation_conditions = list(p.reactivation_conditions)


def _apply_branch_reactivated(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.BranchReactivatedPayload)
    branch = _branch(s, e, p.branch_id)
    if branch is None:
        return
    branch.status = BranchStatus.active
    branch.suspension_reason = None
    branch.reactivation_conditions = []
    branch.consecutive_failures = 0


def _apply_branch_completed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.BranchTerminalPayload)
    branch = _branch(s, e, p.branch_id)
    if branch is not None:
        branch.status = BranchStatus.completed


def _apply_branch_exhausted(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.BranchTerminalPayload)
    branch = _branch(s, e, p.branch_id)
    if branch is not None:
        branch.status = BranchStatus.exhausted
        branch.suspension_reason = p.reason or branch.suspension_reason


def _apply_work_item_created(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, WorkItem)
    item = p.model_copy(deep=True)
    item.created_seq = e.seq
    s.work_items[item.work_item_id] = item
    branch = s.branches.get(item.branch_id)
    if branch is not None and item.work_item_id not in branch.work_item_ids:
        branch.work_item_ids.append(item.work_item_id)
        branch.updated_at = e.timestamp
    _bump_counter(s, ids.WORK_ITEM_PREFIX, item.work_item_id)


def _work_item(s: CampaignSnapshot, e: ev.CampaignEvent, wid: str) -> WorkItem | None:
    item = s.work_items.get(wid)
    if item is None:
        _diag(s, "invalid_payload", f"{e.type} names unknown work item {wid}", e)
    return item


def _apply_work_item_scheduled(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.WorkItemScheduledPayload)
    item = _work_item(s, e, p.work_item_id)
    if item is None:
        return
    item.status = WorkItemStatus.scheduled
    item.scheduled_seq = e.seq
    item.score = p.score
    item.claimed_by = p.claimed_by


def _apply_worker_started(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.WorkerStartedPayload)
    item = _work_item(s, e, p.work_item_id)
    if item is None:
        return
    item.status = WorkItemStatus.running
    item.started_at = e.timestamp
    item.session_id = p.session_id
    item.budget = p.budget
    s.current_worker = CurrentWorker(
        work_item_id=item.work_item_id,
        branch_id=item.branch_id,
        role=p.role,
        session_id=p.session_id,
        started_seq=e.seq,
    )


def _finish_item(s: CampaignSnapshot, e: ev.CampaignEvent, item: WorkItem) -> None:
    item.finished_at = e.timestamp
    if s.current_worker is not None and s.current_worker.work_item_id == item.work_item_id:
        s.current_worker = None


def _apply_worker_completed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.WorkerCompletedPayload)
    item = _work_item(s, e, p.work_item_id)
    if item is None:
        return
    item.status = WorkItemStatus.blocked if p.status == "blocked" else WorkItemStatus.completed
    item.result_status = p.status
    item.usage = p.usage
    for aid in p.artifact_ids:
        if aid not in item.artifact_ids:
            item.artifact_ids.append(aid)
    _finish_item(s, e, item)
    branch = s.branches.get(item.branch_id)
    if branch is not None:
        branch.consecutive_failures = 0
        branch.actual_cost = branch.actual_cost.plus(work_items=1)
        branch.updated_at = e.timestamp


def _apply_worker_failed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.WorkerFailedPayload)
    item = _work_item(s, e, p.work_item_id)
    if item is None:
        return
    item.status = WorkItemStatus.failed
    item.result_status = "failed"
    item.failure_reason = p.message
    item.failure_signature_id = p.failure_signature_id
    _finish_item(s, e, item)
    branch = s.branches.get(item.branch_id)
    if branch is not None:
        branch.consecutive_failures += 1
        branch.actual_cost = branch.actual_cost.plus(work_items=1)
        branch.updated_at = e.timestamp


def _apply_artifact_created(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ArtifactRef)
    ref = p.model_copy(update={"seq": e.seq})
    if ref.branch_id is None and e.branch_id:
        ref.branch_id = e.branch_id
    if ref.work_item_id is None and e.work_item_id:
        ref.work_item_id = e.work_item_id
    if ref.role is None and e.role is not None:
        ref.role = e.role
    _add_ref(s, ref)


def _apply_proof_node_created(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, CampaignNodeState)
    node = p.model_copy(deep=True)
    node.created_seq = node.created_seq or e.seq
    node.updated_seq = e.seq
    s.campaign_nodes[node.node_id] = node
    _bump_counter(s, ids.NODE_PREFIX, node.node_id)


def _apply_proof_node_updated(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.ProofNodeUpdatedPayload)
    node = s.campaign_nodes.get(p.node_id)
    if node is None:
        _diag(s, "invalid_payload", f"proof_node_updated names unknown node {p.node_id}", e)
        return
    known = set(CampaignNodeState.model_fields) - {"node_id", "created_seq", "changes"}
    for key, value in p.changes.items():
        if key in known:
            setattr(node, key, value)
    node.updated_seq = e.seq
    node.changes.append(", ".join(sorted(p.changes)) or "(no fields)")


def _apply_theorem_reference_created(
    s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel
) -> None:
    assert isinstance(p, ev.TheoremReferenceCreatedPayload)
    _add_ref(
        s,
        ArtifactRef(
            artifact_id=p.theorem_reference_id,
            kind="theorem_reference",
            branch_id=e.branch_id,
            work_item_id=e.work_item_id,
            seq=e.seq,
            role=e.role,
        ),
    )


def _apply_review_requested(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    return None


def _apply_review_recorded(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ReviewRef)
    s.reviews.append(p.model_copy(update={"seq": e.seq}))


def _apply_verification_requested(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    return None


def _apply_verification_recorded(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, VerificationRef)
    s.verifications.append(p.model_copy(update={"seq": e.seq}))


def _apply_budget_consumed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.BudgetConsumedPayload)
    ledger = s.budget
    ledger.steps_used += p.steps
    ledger.tokens_used += p.tokens
    ledger.cost_used_usd += p.cost_usd
    ledger.wall_seconds_used += p.wall_seconds
    if p.scope == "model_invocation":
        ledger.model_invocations += 1
    elif p.scope == "tool_execution":
        ledger.tool_executions += 1
    elif p.scope == "experiment":
        ledger.experiments_run += 1
    if p.scope == "work_item" and p.ref:
        _charge(ledger, p.ref, ledger.per_work_item, p)
        s.steps_executed += p.steps
        item = s.work_items.get(p.ref)
        if item is not None:
            _charge(ledger, item.branch_id, ledger.per_branch, p)
            branch = s.branches.get(item.branch_id)
            if branch is not None:
                branch.actual_cost = branch.actual_cost.plus(
                    steps=p.steps, tokens=p.tokens, cost_usd=p.cost_usd, wall_seconds=p.wall_seconds
                )
    elif p.scope == "branch" and p.ref:
        _charge(ledger, p.ref, ledger.per_branch, p)


def _apply_budget_exhausted(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.BudgetExhaustedPayload)
    if p.axis not in s.budget.exhausted:
        s.budget.exhausted.append(p.axis)


def _apply_routing_decision_recorded(
    s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel
) -> None:
    assert isinstance(p, RouteSummary)
    if p.decision_id not in s.routing_decision_ids:
        s.routing_decision_ids.append(p.decision_id)
    s.last_route = RouteSummary.model_validate(p.model_dump())
    if e.work_item_id and e.work_item_id in s.work_items:
        s.work_items[e.work_item_id].routing_decision_id = p.decision_id


def _apply_campaign_paused(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.CampaignPausedPayload)
    resume = p.resume_phase
    if not _enter_phase(s, e, CampaignPhase.PAUSED, reason=p.reason):
        return
    s.resume_phase = resume
    s.pause_reason = p.reason
    s.status = CampaignStatus.paused
    # No worker survives a pause (the engine process stops); a still-running work
    # item is failed on resume by the engine.
    s.current_worker = None


def _apply_campaign_resumed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.CampaignResumedPayload)
    if not _enter_phase(s, e, p.resume_phase, reason=p.note or "resumed"):
        return
    s.status = CampaignStatus.running
    s.pause_reason = None


def _apply_campaign_stopped(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.CampaignStoppedPayload)
    if not _enter_phase(s, e, CampaignPhase.STOPPED, reason=p.reason):
        return
    s.status = CampaignStatus.stopped
    s.stop_reason = p.reason
    s.ended_at = e.timestamp
    s.current_worker = None


def _apply_campaign_completed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.CampaignCompletedPayload)
    if not _enter_phase(s, e, CampaignPhase.COMPLETED, reason=p.reason):
        return
    s.status = CampaignStatus.completed
    s.completion_reason = p.reason
    s.ended_at = e.timestamp
    s.current_worker = None


def _apply_campaign_failed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.CampaignFailedPayload)
    if not _enter_phase(s, e, CampaignPhase.FAILED, reason=p.reason):
        return
    s.status = CampaignStatus.failed
    s.failure_reason = p.reason
    s.ended_at = e.timestamp
    s.current_worker = None


def _apply_obligation_created(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, Obligation)
    ob = p.model_copy(deep=True)
    ob.created_seq = ob.created_seq or e.seq
    ob.updated_seq = e.seq
    s.obligations[ob.obligation_id] = ob
    _bump_counter(s, ids.OBLIGATION_PREFIX, ob.obligation_id)


def _apply_obligation_updated(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.ObligationUpdatedPayload)
    ob = s.obligations.get(p.obligation_id)
    if ob is None:
        _diag(s, "invalid_payload", f"obligation_updated names unknown {p.obligation_id}", e)
        return
    known = set(Obligation.model_fields) - {"obligation_id", "campaign_id", "created_seq"}
    for key, value in p.changes.items():
        if key in known:
            setattr(ob, key, value)
    ob.updated_seq = e.seq


def _apply_obligation_closed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.ObligationClosedPayload)
    ob = s.obligations.get(p.obligation_id)
    if ob is None:
        _diag(s, "invalid_payload", f"obligation_closed names unknown {p.obligation_id}", e)
        return
    ob.status = ObligationStatus.closed
    ob.closed_by_artifact = p.artifact_id
    ob.closed_by_mode = p.closure_mode
    ob.closed_by_check = p.check_id
    if p.artifact_id not in ob.supporting_artifacts:
        ob.supporting_artifacts.append(p.artifact_id)
    ob.updated_seq = e.seq


def _apply_failure_signature_recorded(
    s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel
) -> None:
    assert isinstance(p, FailureSignature)
    sig = p.model_copy(deep=True)
    existing = s.failure_signatures.get(sig.signature_id)
    if existing is not None:
        existing.occurrences += 1
        existing.last_seq = e.seq
        for aid in sig.artifact_ids:
            if aid not in existing.artifact_ids:
                existing.artifact_ids.append(aid)
        sig = existing
    else:
        sig.first_seq = sig.first_seq or e.seq
        sig.last_seq = e.seq
        s.failure_signatures[sig.signature_id] = sig
    _bump_counter(s, ids.FAILURE_SIGNATURE_PREFIX, sig.signature_id)
    bid = sig.branch_id or e.branch_id
    if bid and bid in s.branches and sig.signature_id not in s.branches[bid].failure_signatures:
        s.branches[bid].failure_signatures.append(sig.signature_id)


def _apply_retry_refused(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.RetryRefusedPayload)
    sig = s.failure_signatures.get(p.signature_id)
    if sig is not None:
        sig.retry_notes.append(f"refused at seq {e.seq}: {p.reason_code} {p.why_refused}".strip())


def _apply_coverage_assessed(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.CoverageAssessedPayload)
    s.coverage_ref = p.coverage_ref
    s.insufficient_categories = list(p.insufficient)


def _apply_migration_recorded(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.MigrationRecordedPayload)
    _diag(s, "migration", f"imported from {', '.join(p.source_paths) or '(unknown)'}", e)


def _apply_diagnostic_recorded(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, Diagnostic)
    diag = p.model_copy()
    if diag.seq is None:
        diag.seq = e.seq
    if diag.recorded_at is None:
        diag.recorded_at = e.timestamp
    s.diagnostics.append(diag)


def _apply_parallelism_capped(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, ev.ParallelismCappedPayload)
    _diag(
        s,
        "parallelism_capped",
        f"max_parallel_workers={p.requested} requested; this version runs {p.effective} "
        "worker at a time",
        e,
    )


def _apply_problem_normalized(s: CampaignSnapshot, e: ev.CampaignEvent, p: BaseModel) -> None:
    assert isinstance(p, NormalizedProblem)
    s.normalized_problem = p.model_copy(deep=True)


_HANDLERS: dict[str, Handler] = {
    ev.EventType.campaign_created: _apply_campaign_created,
    ev.EventType.campaign_started: _apply_campaign_started,
    ev.EventType.phase_entered: _apply_phase_entered,
    ev.EventType.phase_completed: _apply_phase_completed,
    ev.EventType.branch_proposed: _apply_branch_proposed,
    ev.EventType.branch_rejected: _apply_branch_rejected,
    ev.EventType.branch_activated: _apply_branch_activated,
    ev.EventType.branch_suspended: _apply_branch_suspended,
    ev.EventType.branch_reactivated: _apply_branch_reactivated,
    ev.EventType.branch_completed: _apply_branch_completed,
    ev.EventType.branch_exhausted: _apply_branch_exhausted,
    ev.EventType.work_item_created: _apply_work_item_created,
    ev.EventType.work_item_scheduled: _apply_work_item_scheduled,
    ev.EventType.worker_started: _apply_worker_started,
    ev.EventType.worker_completed: _apply_worker_completed,
    ev.EventType.worker_failed: _apply_worker_failed,
    ev.EventType.artifact_created: _apply_artifact_created,
    ev.EventType.proof_node_created: _apply_proof_node_created,
    ev.EventType.proof_node_updated: _apply_proof_node_updated,
    ev.EventType.theorem_reference_created: _apply_theorem_reference_created,
    ev.EventType.review_requested: _apply_review_requested,
    ev.EventType.review_recorded: _apply_review_recorded,
    ev.EventType.verification_requested: _apply_verification_requested,
    ev.EventType.verification_recorded: _apply_verification_recorded,
    ev.EventType.budget_consumed: _apply_budget_consumed,
    ev.EventType.budget_exhausted: _apply_budget_exhausted,
    ev.EventType.routing_decision_recorded: _apply_routing_decision_recorded,
    ev.EventType.campaign_paused: _apply_campaign_paused,
    ev.EventType.campaign_resumed: _apply_campaign_resumed,
    ev.EventType.campaign_stopped: _apply_campaign_stopped,
    ev.EventType.campaign_completed: _apply_campaign_completed,
    ev.EventType.campaign_failed: _apply_campaign_failed,
    ev.EventType.obligation_created: _apply_obligation_created,
    ev.EventType.obligation_updated: _apply_obligation_updated,
    ev.EventType.obligation_closed: _apply_obligation_closed,
    ev.EventType.failure_signature_recorded: _apply_failure_signature_recorded,
    ev.EventType.retry_refused: _apply_retry_refused,
    ev.EventType.coverage_assessed: _apply_coverage_assessed,
    ev.EventType.migration_recorded: _apply_migration_recorded,
    ev.EventType.diagnostic_recorded: _apply_diagnostic_recorded,
    ev.EventType.parallelism_capped: _apply_parallelism_capped,
    ev.EventType.problem_normalized: _apply_problem_normalized,
}


# --------------------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------------------


def empty_snapshot(created: ev.CampaignEvent) -> CampaignSnapshot:
    """The initial state, seeded from the ``campaign_created`` event's record.

    Budget limits are copied from the config snapshot (``0`` = unlimited); every
    id counter starts at zero; the CREATED phase entry is the first history line.
    """
    if created.type != ev.EventType.campaign_created:
        raise ValueError(f"the first event must be campaign_created, got {created.type}")
    record = CampaignRecord.model_validate(created.payload)
    cfg = record.config_snapshot
    snapshot = CampaignSnapshot(
        campaign_id=record.id,
        problem_id=record.problem_id,
        mode=record.mode,
        phase=CampaignPhase.CREATED,
        status=CampaignStatus.created,
        last_seq=created.seq,
        last_event_id=created.event_id,
        created_at=created.timestamp,
        updated_at=created.timestamp,
        budget=BudgetLedger(
            steps_limit=cfg.max_steps,
            token_limit=cfg.token_budget,
            cost_limit_usd=cfg.cost_budget,
            wall_limit=cfg.max_wall_seconds,
        ),
        counters={prefix: 0 for prefix in ids.COUNTER_PREFIXES},
        phase_history=[
            PhaseEntry(
                phase=CampaignPhase.CREATED,
                from_phase=None,
                entered_seq=created.seq,
                entered_at=created.timestamp,
                reason="created",
            )
        ],
        recent_event_ids=[created.event_id],
    )
    return snapshot


def apply(snapshot: CampaignSnapshot, event: ev.CampaignEvent) -> CampaignSnapshot:
    """Fold one event into a *new* snapshot (the input is never mutated)."""
    new = snapshot.model_copy(deep=True)
    if event.seq <= new.last_seq:
        _diag(
            new,
            "seq_duplicate",
            f"event {event.event_id} (seq {event.seq}) does not advance last_seq {new.last_seq}",
            event,
        )
        return new
    new.last_seq = event.seq
    new.last_event_id = event.event_id
    new.updated_at = event.timestamp
    new.recent_event_ids.append(event.event_id)
    if len(new.recent_event_ids) > RECENT_EVENTS_KEPT:
        del new.recent_event_ids[: len(new.recent_event_ids) - RECENT_EVENTS_KEPT]

    handler = _HANDLERS.get(event.type)
    if handler is None:
        _diag(new, "unknown_event_type", f"unknown event type '{event.type}' ignored", event)
        return new
    try:
        payload = event.typed_payload()
    except ValidationError as exc:
        _diag(
            new, "invalid_payload", f"{event.type}: {exc.error_count()} validation error(s)", event
        )
        return new
    if payload is None:  # pragma: no cover - registry and handler tables agree
        _diag(new, "unknown_event_type", f"unregistered event type '{event.type}'", event)
        return new
    handler(new, event, payload)
    return new


def reduce(events: Iterable[ev.CampaignEvent]) -> CampaignSnapshot:
    """Fold a whole log. Raises ``ValueError`` when the log does not start with
    ``campaign_created`` (there is nothing to seed a snapshot from)."""
    iterator = iter(events)
    try:
        first = next(iterator)
    except StopIteration as exc:
        raise ValueError("cannot reduce an empty event log") from exc
    snapshot = empty_snapshot(first)
    for event in iterator:
        snapshot = apply(snapshot, event)
    return snapshot


def phase_history(snapshot: CampaignSnapshot) -> list[PhaseEntry]:
    return list(snapshot.phase_history)


def recent_event_ids(snapshot: CampaignSnapshot) -> list[str]:
    return list(snapshot.recent_event_ids[-RECENT_EVENTS_KEPT:])


__all__ = [
    "RECENT_EVENTS_KEPT",
    "apply",
    "empty_snapshot",
    "phase_history",
    "recent_event_ids",
    "reduce",
]
