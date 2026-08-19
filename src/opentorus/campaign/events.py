"""The campaign event envelope, the typed payload registry, and the parser.

An event is the unit of truth in a campaign: ``events.jsonl`` is append-only and
every line is a :class:`CampaignEvent` whose ``payload`` is validated against the
model registered for its ``type`` in :data:`EVENT_PAYLOADS`. Unknown types are
*preserved* (the envelope still parses, ``payload`` is kept raw) so a log written by
a newer build stays readable — the reducer records a diagnostic and ignores them.

The registry covers every event type named in the assignment
(:data:`ASSIGNMENT_EVENT_TYPES`, pinned by a test) plus the extras the engine needs
to be honest about failures, obligations, coverage and migrations.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from opentorus.campaign.models import (
    SCHEMA_VERSION,
    ArtifactRef,
    BranchRecord,
    BudgetScope,
    CampaignConfigSnapshot,
    CampaignMode,
    CampaignNodeState,
    CampaignPhase,
    CampaignRecord,
    ClosureMode,
    CostTotals,
    Diagnostic,
    ErrorCategory,
    FailureSignature,
    NormalizedProblem,
    Obligation,
    ReactivationCondition,
    ReviewRef,
    RouteSummary,
    ScoreBreakdown,
    VerificationRef,
    WorkBudget,
    WorkerRole,
    WorkItem,
)


class EventType(StrEnum):
    # -- assignment types ------------------------------------------------------------
    campaign_created = "campaign_created"
    campaign_started = "campaign_started"
    phase_entered = "phase_entered"
    phase_completed = "phase_completed"
    branch_proposed = "branch_proposed"
    branch_rejected = "branch_rejected"
    branch_activated = "branch_activated"
    branch_suspended = "branch_suspended"
    branch_reactivated = "branch_reactivated"
    work_item_created = "work_item_created"
    work_item_scheduled = "work_item_scheduled"
    worker_started = "worker_started"
    worker_completed = "worker_completed"
    worker_failed = "worker_failed"
    artifact_created = "artifact_created"
    proof_node_created = "proof_node_created"
    proof_node_updated = "proof_node_updated"
    theorem_reference_created = "theorem_reference_created"
    review_requested = "review_requested"
    review_recorded = "review_recorded"
    verification_requested = "verification_requested"
    verification_recorded = "verification_recorded"
    budget_consumed = "budget_consumed"
    budget_exhausted = "budget_exhausted"
    routing_decision_recorded = "routing_decision_recorded"
    campaign_paused = "campaign_paused"
    campaign_resumed = "campaign_resumed"
    campaign_stopped = "campaign_stopped"
    campaign_completed = "campaign_completed"
    # -- extras ----------------------------------------------------------------------
    branch_completed = "branch_completed"
    branch_exhausted = "branch_exhausted"
    obligation_created = "obligation_created"
    obligation_updated = "obligation_updated"
    obligation_closed = "obligation_closed"
    failure_signature_recorded = "failure_signature_recorded"
    retry_refused = "retry_refused"
    coverage_assessed = "coverage_assessed"
    migration_recorded = "migration_recorded"
    diagnostic_recorded = "diagnostic_recorded"
    campaign_failed = "campaign_failed"
    parallelism_capped = "parallelism_capped"
    problem_normalized = "problem_normalized"
    branch_updated = "branch_updated"
    retry_allowed = "retry_allowed"


ASSIGNMENT_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "campaign_created",
        "campaign_started",
        "phase_entered",
        "phase_completed",
        "branch_proposed",
        "branch_rejected",
        "branch_activated",
        "branch_suspended",
        "branch_reactivated",
        "work_item_created",
        "work_item_scheduled",
        "worker_started",
        "worker_completed",
        "worker_failed",
        "artifact_created",
        "proof_node_created",
        "proof_node_updated",
        "theorem_reference_created",
        "review_requested",
        "review_recorded",
        "verification_requested",
        "verification_recorded",
        "budget_consumed",
        "budget_exhausted",
        "routing_decision_recorded",
        "campaign_paused",
        "campaign_resumed",
        "campaign_stopped",
        "campaign_completed",
    }
)


# --------------------------------------------------------------------------------------
# Payload models (small, typed; ``extra="allow"`` so a newer field survives)
# --------------------------------------------------------------------------------------


class _Payload(BaseModel):
    model_config = ConfigDict(extra="allow")


class CampaignStartedPayload(_Payload):
    problem_id: str
    mode: CampaignMode
    config_snapshot: CampaignConfigSnapshot


class PhaseEnteredPayload(_Payload):
    phase: CampaignPhase
    from_phase: CampaignPhase | None = None
    reason: str = ""


class PhaseCompletedPayload(_Payload):
    phase: CampaignPhase
    outcome: str = ""
    next_phase: CampaignPhase | None = None


class BranchRejectedPayload(_Payload):
    branch_id: str
    reason_code: str
    duplicate_of: str | None = None
    note: str = ""


class BranchActivatedPayload(_Payload):
    branch_id: str
    priority: float = 1.0
    slot: int = 0


class BranchSuspendedPayload(_Payload):
    branch_id: str
    reason_code: str
    reactivation_conditions: list[ReactivationCondition] = Field(default_factory=list)


class BranchReactivatedPayload(_Payload):
    branch_id: str
    condition_met: ReactivationCondition
    observed: str = ""


class BranchTerminalPayload(_Payload):
    """``branch_completed`` / ``branch_exhausted``."""

    branch_id: str
    reason: str = ""


class WorkItemScheduledPayload(_Payload):
    work_item_id: str
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    claimed_by: str = "engine"


class WorkerStartedPayload(_Payload):
    work_item_id: str
    role: WorkerRole
    session_id: str
    budget: WorkBudget


class WorkerCompletedPayload(_Payload):
    work_item_id: str
    status: str
    usage: CostTotals = Field(default_factory=CostTotals)
    artifact_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WorkerFailedPayload(_Payload):
    work_item_id: str
    error_category: ErrorCategory = "other"
    message: str = ""
    failure_signature_id: str | None = None


class ProofNodeUpdatedPayload(_Payload):
    node_id: str
    changes: dict[str, object] = Field(default_factory=dict)


class TheoremReferenceCreatedPayload(_Payload):
    theorem_reference_id: str
    paper_id: str = ""
    review_status: str = "candidate"


class ReviewRequestedPayload(_Payload):
    target_id: str
    kind: str = "review"


class VerificationRequestedPayload(_Payload):
    artifact_id: str
    backend: str = ""


class BudgetConsumedPayload(_Payload):
    scope: BudgetScope = "work_item"
    ref: str = ""
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    wall_seconds: float = 0.0


class BudgetExhaustedPayload(_Payload):
    axis: str
    used: float
    limit: float
    scope: BudgetScope = "campaign"


class RoutingDecisionRecordedPayload(RouteSummary):
    pass


class CampaignPausedPayload(_Payload):
    reason: str
    resume_phase: CampaignPhase


class CampaignResumedPayload(_Payload):
    """``from_phase`` is where the campaign was paused (``PAUSED``); ``resume_phase``
    is the working phase it returns to."""

    from_phase: CampaignPhase = CampaignPhase.PAUSED
    resume_phase: CampaignPhase
    note: str = ""


class CampaignStoppedPayload(_Payload):
    reason: str


class CampaignCompletedPayload(_Payload):
    reason: str
    mode_criterion: str = ""


class ObligationUpdatedPayload(_Payload):
    obligation_id: str
    changes: dict[str, object] = Field(default_factory=dict)


class ObligationClosedPayload(_Payload):
    obligation_id: str
    artifact_id: str
    closure_mode: ClosureMode
    check_id: str | None = None
    verdict: str = ""


class RetryRefusedPayload(_Payload):
    branch_id: str
    signature_id: str
    reason_code: str
    why_refused: str = ""


class RetryAllowedPayload(_Payload):
    """A retry of a recorded failure was permitted because something changed;
    ``why_different`` is appended to the signature's ``retry_notes``."""

    branch_id: str
    signature_id: str
    reason_code: str = "OK"
    why_different: str = ""


class BranchUpdatedPayload(_Payload):
    """Field changes on an existing branch (e.g. the target claim a worker picked)."""

    branch_id: str
    changes: dict[str, object] = Field(default_factory=dict)


class CoverageAssessedPayload(_Payload):
    coverage_ref: str
    insufficient: list[str] = Field(default_factory=list)
    critical: list[str] = Field(default_factory=list)


class MigrationRecordedPayload(_Payload):
    source_paths: list[str] = Field(default_factory=list)
    sha256s: list[str] = Field(default_factory=list)
    imported_at: datetime | None = None
    importer_version: str = ""


class CampaignFailedPayload(_Payload):
    reason: str


class ParallelismCappedPayload(_Payload):
    requested: int
    effective: int


EVENT_PAYLOADS: dict[str, type[BaseModel]] = {
    EventType.campaign_created: CampaignRecord,
    EventType.campaign_started: CampaignStartedPayload,
    EventType.phase_entered: PhaseEnteredPayload,
    EventType.phase_completed: PhaseCompletedPayload,
    EventType.branch_proposed: BranchRecord,
    EventType.branch_rejected: BranchRejectedPayload,
    EventType.branch_activated: BranchActivatedPayload,
    EventType.branch_suspended: BranchSuspendedPayload,
    EventType.branch_reactivated: BranchReactivatedPayload,
    EventType.branch_completed: BranchTerminalPayload,
    EventType.branch_exhausted: BranchTerminalPayload,
    EventType.work_item_created: WorkItem,
    EventType.work_item_scheduled: WorkItemScheduledPayload,
    EventType.worker_started: WorkerStartedPayload,
    EventType.worker_completed: WorkerCompletedPayload,
    EventType.worker_failed: WorkerFailedPayload,
    EventType.artifact_created: ArtifactRef,
    EventType.proof_node_created: CampaignNodeState,
    EventType.proof_node_updated: ProofNodeUpdatedPayload,
    EventType.theorem_reference_created: TheoremReferenceCreatedPayload,
    EventType.review_requested: ReviewRequestedPayload,
    EventType.review_recorded: ReviewRef,
    EventType.verification_requested: VerificationRequestedPayload,
    EventType.verification_recorded: VerificationRef,
    EventType.budget_consumed: BudgetConsumedPayload,
    EventType.budget_exhausted: BudgetExhaustedPayload,
    EventType.routing_decision_recorded: RoutingDecisionRecordedPayload,
    EventType.campaign_paused: CampaignPausedPayload,
    EventType.campaign_resumed: CampaignResumedPayload,
    EventType.campaign_stopped: CampaignStoppedPayload,
    EventType.campaign_completed: CampaignCompletedPayload,
    EventType.obligation_created: Obligation,
    EventType.obligation_updated: ObligationUpdatedPayload,
    EventType.obligation_closed: ObligationClosedPayload,
    EventType.failure_signature_recorded: FailureSignature,
    EventType.retry_refused: RetryRefusedPayload,
    EventType.coverage_assessed: CoverageAssessedPayload,
    EventType.migration_recorded: MigrationRecordedPayload,
    EventType.diagnostic_recorded: Diagnostic,
    EventType.campaign_failed: CampaignFailedPayload,
    EventType.parallelism_capped: ParallelismCappedPayload,
    EventType.problem_normalized: NormalizedProblem,
    EventType.branch_updated: BranchUpdatedPayload,
    EventType.retry_allowed: RetryAllowedPayload,
}


# --------------------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------------------


class CampaignEvent(BaseModel):
    """One line of ``events.jsonl``.

    ``seq`` is the 1-based position in the log and ``event_id`` is derived from it;
    ``causation_id`` names the event that triggered this one and ``correlation_id``
    groups the events of one work item, so a reader can follow a chain without
    the engine's help. ``payload`` is a plain dict — validated by :func:`parse_event`
    against the registry, kept raw when the type is unknown.
    """

    model_config = ConfigDict(extra="allow")

    event_id: str
    campaign_id: str
    seq: int
    schema_version: int = SCHEMA_VERSION
    timestamp: datetime
    type: str
    actor: str = "engine"
    role: WorkerRole | None = None
    refs: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)
    causation_id: str | None = None
    correlation_id: str | None = None
    work_item_id: str | None = None
    branch_id: str | None = None

    def typed_payload(self) -> BaseModel | None:
        """The payload validated as its registered model, or ``None`` when unknown."""
        model = EVENT_PAYLOADS.get(self.type)
        if model is None:
            return None
        return model.model_validate(self.payload)


class UnknownEventError(ValueError):
    """Raised by :func:`parse_event` only for envelopes that are not events at all."""


def is_known_type(event: CampaignEvent) -> bool:
    return event.type in EVENT_PAYLOADS


def payload_to_dict(payload: BaseModel | dict[str, object]) -> dict[str, object]:
    """JSON-mode dump of a payload model (datetimes/enums become strings)."""
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    return dict(payload)


def validate_payload(event_type: str, payload: BaseModel | dict[str, object]) -> dict[str, object]:
    """Validate ``payload`` against the model registered for ``event_type``.

    Unknown types pass through untouched (raw dict); a known type with an invalid
    payload raises :class:`pydantic.ValidationError` — the engine must never write a
    line the reducer cannot read.
    """
    model = EVENT_PAYLOADS.get(event_type)
    if model is None:
        return payload_to_dict(payload)
    if isinstance(payload, model):
        return payload.model_dump(mode="json")
    return model.model_validate(payload_to_dict(payload)).model_dump(mode="json")


def build_event(
    *,
    campaign_id: str,
    seq: int,
    timestamp: datetime,
    event_type: str,
    payload: BaseModel | dict[str, object],
    actor: str = "engine",
    role: WorkerRole | None = None,
    refs: list[str] | tuple[str, ...] = (),
    causation_id: str | None = None,
    correlation_id: str | None = None,
    work_item_id: str | None = None,
    branch_id: str | None = None,
) -> CampaignEvent:
    """Fill the envelope: ``event_id`` from ``seq``, payload validated against the registry."""
    from opentorus.campaign.ids import event_id

    return CampaignEvent(
        event_id=event_id(seq),
        campaign_id=campaign_id,
        seq=seq,
        schema_version=SCHEMA_VERSION,
        timestamp=timestamp,
        type=str(event_type),
        actor=actor,
        role=role,
        refs=list(refs),
        payload=validate_payload(str(event_type), payload),
        causation_id=causation_id,
        correlation_id=correlation_id,
        work_item_id=work_item_id,
        branch_id=branch_id,
    )


def parse_event(raw: dict[str, object]) -> CampaignEvent:
    """Parse one JSON object into a :class:`CampaignEvent`.

    The envelope must validate (else :class:`UnknownEventError`); a known type's
    payload is validated too so a corrupt-but-parseable line surfaces as an error the
    store turns into a diagnostic. Unknown types are kept as-is.
    """
    try:
        event = CampaignEvent.model_validate(raw)
    except ValidationError as exc:
        raise UnknownEventError(f"not a campaign event: {exc}") from exc
    model = EVENT_PAYLOADS.get(event.type)
    if model is not None:
        try:
            model.model_validate(event.payload)
        except ValidationError as exc:
            raise UnknownEventError(f"invalid payload for {event.type}: {exc}") from exc
    return event


__all__ = [
    "ASSIGNMENT_EVENT_TYPES",
    "EVENT_PAYLOADS",
    "BranchActivatedPayload",
    "BranchReactivatedPayload",
    "BranchRejectedPayload",
    "BranchSuspendedPayload",
    "BranchTerminalPayload",
    "BranchUpdatedPayload",
    "BudgetConsumedPayload",
    "BudgetExhaustedPayload",
    "CampaignCompletedPayload",
    "CampaignEvent",
    "CampaignFailedPayload",
    "CampaignPausedPayload",
    "CampaignResumedPayload",
    "CampaignStartedPayload",
    "CampaignStoppedPayload",
    "CoverageAssessedPayload",
    "EventType",
    "MigrationRecordedPayload",
    "ObligationClosedPayload",
    "ObligationUpdatedPayload",
    "ParallelismCappedPayload",
    "PhaseCompletedPayload",
    "PhaseEnteredPayload",
    "ProofNodeUpdatedPayload",
    "RetryRefusedPayload",
    "RetryAllowedPayload",
    "ReviewRequestedPayload",
    "RoutingDecisionRecordedPayload",
    "TheoremReferenceCreatedPayload",
    "UnknownEventError",
    "VerificationRequestedPayload",
    "WorkItemScheduledPayload",
    "WorkerCompletedPayload",
    "WorkerFailedPayload",
    "WorkerStartedPayload",
    "build_event",
    "is_known_type",
    "parse_event",
    "payload_to_dict",
    "validate_payload",
]
