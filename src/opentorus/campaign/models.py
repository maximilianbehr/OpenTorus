"""Typed campaign records: enums, persisted records, and the reducer's snapshot.

Everything a campaign persists is one of these models. Persisted records use
``extra="allow"`` so a newer build's fields survive a round trip through an older
one (the store never drops what it does not understand). The snapshot holds
orchestration state and *references* to dossier artifacts only — no claim status,
no root mathematical status — because those are derived from the dossier on demand
and must never be copied into a place where they could go stale or be edited.

``SCHEMA_VERSION`` stamps every event and snapshot; ``store.migrate_events`` upgrades
older records on read.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from opentorus.config import SchedulerWeights

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------------------


class CampaignMode(StrEnum):
    """What the campaign is for; the values equal ``config.CampaignMode``'s literals."""

    prove_or_refute = "prove-or-refute"
    exploration = "exploration"
    survey = "survey"


class CampaignPhase(StrEnum):
    """The engine's phase; the transition table lives in :mod:`phases`."""

    CREATED = "created"
    INGEST = "ingest"
    NORMALIZE = "normalize"
    MAP_LITERATURE = "map-literature"
    GENERATE_PORTFOLIO = "generate-portfolio"
    SCHEDULE = "schedule"
    EXECUTE = "execute"
    CRITIQUE = "critique"
    VERIFY = "verify"
    UPDATE_GRAPH = "update-graph"
    REALLOCATE = "reallocate"
    SYNTHESIZE = "synthesize"
    COMPLETED = "completed"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"


class CampaignStatus(StrEnum):
    created = "created"
    running = "running"
    paused = "paused"
    stopped = "stopped"
    completed = "completed"
    failed = "failed"


class BranchKind(StrEnum):
    proof = "proof"
    counterexample = "counterexample"
    literature = "literature"
    special_case = "special-case"
    symbolic = "symbolic"
    numerical = "numerical"
    formalization = "formalization"
    obstruction = "obstruction"
    synthesis = "synthesis"


class BranchStatus(StrEnum):
    proposed = "proposed"
    rejected = "rejected"
    active = "active"
    suspended = "suspended"
    exhausted = "exhausted"
    completed = "completed"


class RootRelation(StrEnum):
    """How a branch's target relates to the root problem (settlement rules in M5).

    Values equal ``research.theorems.models.ROOT_RELATIONS`` — pinned by a test — so
    theorem references and branches speak the same vocabulary without an import.
    """

    equivalent = "equivalent"
    sufficient = "sufficient"
    necessary = "necessary"
    special_case = "special-case"
    relaxation = "relaxation"
    counterexample_route = "counterexample-route"
    supporting = "supporting"
    unrelated = "unrelated"
    unknown = "unknown"


class WorkerRole(StrEnum):
    strategist = "strategist"
    prover = "prover"
    falsifier = "falsifier"
    librarian = "librarian"
    symbolic_experimenter = "symbolic-experimenter"
    numerical_experimenter = "numerical-experimenter"
    formalizer = "formalizer"
    critic = "critic"
    verifier_coordinator = "verifier-coordinator"
    synthesizer = "synthesizer"


class WorkItemStatus(StrEnum):
    created = "created"
    scheduled = "scheduled"
    running = "running"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"
    cancelled = "cancelled"


class ObligationStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"
    contradicted = "contradicted"
    abandoned = "abandoned"


class ClosureMode(StrEnum):
    """The only ways an obligation may close; each names the artifact class required."""

    nl_proof_referee_accepted = "nl_proof_referee_accepted"
    formal_proof = "formal_proof"
    smt_certificate = "smt_certificate"
    exact_symbolic_certificate = "exact_symbolic_certificate"
    validated_numerical_certificate = "validated_numerical_certificate"
    accepted_literature_theorem = "accepted_literature_theorem"
    accepted_counterexample_certificate = "accepted_counterexample_certificate"


WorkerResultStatus = Literal["completed", "failed", "blocked", "branch_done"]
ErrorCategory = Literal[
    "tool_unavailable",
    "verifier_rejected",
    "verifier_inconclusive",
    "no_witness_found",
    # A search ran but its output could not be parsed as a search result: the witness
    # status is unknown and must never be asserted as "no witness found". (A live
    # falsifier once printed "CONFIRMED: This is a counterexample!" in free text and
    # the canned no-witness signature buried it.)
    "witness_unconfirmed",
    "citation_invalid",
    "permission_blocked",
    "budget",
    "timeout",
    "model_no_progress",
    # The provider (or the network to it) failed — an operational condition, not a
    # mathematical dead end. Three of these in a row pause the campaign instead of
    # letting every model-driven branch burn its budget against a dead endpoint.
    "provider_unavailable",
    "other",
]
DiagnosticKind = Literal[
    "corrupt_line",
    "corrupt_snapshot",
    "seq_gap",
    "seq_duplicate",
    "unknown_event_type",
    "invalid_payload",
    "invalid_transition",
    "migration",
    "parallelism_capped",
    # verify: snapshot.json covers only a prefix of the log (persist_every_event=false),
    # so "replay matches snapshot" verified only that prefix.
    "snapshot_lag",
]
ReactivationKind = Literal[
    "new_evidence_count",
    "theorem_ref_accepted",
    "assumption_changed",
    "obligation_closed",
    "verification_backend_changed",
    "human_override",
    "branch_completed",
    "campaign_resumed",
]
BudgetScope = Literal[
    "campaign", "branch", "work_item", "model_invocation", "tool_execution", "experiment"
]


class _Persisted(BaseModel):
    """Base for records that live in the event log / snapshot: unknown fields survive."""

    model_config = ConfigDict(extra="allow")


# --------------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------------


class CampaignConfigSnapshot(_Persisted):
    """The effective configuration a campaign was started with (config + CLI flags).

    Frozen into ``campaign.yaml`` so a resume months later runs under the same rules,
    and so ``0 = unlimited`` on every budget axis is auditable. The governance caps
    are copied for the same reason: they bound the campaign as a whole.
    """

    mode: CampaignMode = CampaignMode.exploration
    initial_branches: int = 4
    max_active_branches: int = 3
    max_parallel_workers: int = 1
    max_steps: int = 50
    max_wall_seconds: int = 0
    token_budget: int = 0
    cost_budget: float = 0.0
    branch_step_budget: int = 10
    require_literature_mapping: bool = True
    require_root_relation: bool = True
    persist_every_event: bool = True
    scheduler_weights: SchedulerWeights = Field(default_factory=SchedulerWeights)
    governance_token_budget: int | None = None
    governance_cost_budget_usd: float | None = None


class CampaignRecord(_Persisted):
    """``campaign.yaml``: identity and provenance of one campaign (never rewritten)."""

    id: str
    problem_id: str
    mode: CampaignMode
    schema_version: int = SCHEMA_VERSION
    created_at: datetime
    statement_sha256: str = ""
    config_snapshot: CampaignConfigSnapshot = Field(default_factory=CampaignConfigSnapshot)
    imported_from: str | None = None
    migration_provenance: dict[str, object] | None = None
    created_by: str = "cli"
    primary_claim_id: str | None = None


class CostTotals(_Persisted):
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    work_items: int = 0
    wall_seconds: float = 0.0

    def plus(
        self,
        *,
        steps: int = 0,
        tokens: int = 0,
        cost_usd: float = 0.0,
        work_items: int = 0,
        wall_seconds: float = 0.0,
    ) -> CostTotals:
        return CostTotals(
            steps=self.steps + steps,
            tokens=self.tokens + tokens,
            cost_usd=self.cost_usd + cost_usd,
            work_items=self.work_items + work_items,
            wall_seconds=self.wall_seconds + wall_seconds,
        )


class ReactivationCondition(_Persisted):
    kind: ReactivationKind
    reference: str | None = None
    threshold: float | None = None
    observed_at_suspension: float | None = None


class BranchRecord(_Persisted):
    """One line of attack; ``root_relation`` says what settling it would mean for the root."""

    branch_id: str
    campaign_id: str
    title: str
    kind: BranchKind
    objective: str
    strategy_summary: str = ""
    root_relation: RootRelation = RootRelation.unknown
    assumption_context: list[str] = Field(default_factory=list)
    parent_branch_id: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    status: BranchStatus = BranchStatus.proposed
    priority: float = 1.0
    estimated_cost: float = 0.0
    actual_cost: CostTotals = Field(default_factory=CostTotals)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    assigned_worker_role: WorkerRole = WorkerRole.strategist
    artifact_references: list[str] = Field(default_factory=list)
    failure_signatures: list[str] = Field(default_factory=list)
    suspension_reason: str | None = None
    reactivation_conditions: list[ReactivationCondition] = Field(default_factory=list)
    approach_id: str | None = None
    rejection_reason: str | None = None
    duplicate_of: str | None = None
    distinctness_note: str = ""
    work_item_ids: list[str] = Field(default_factory=list)
    consecutive_failures: int = 0
    target_claim_id: str | None = None
    strategy_key: str | None = None


class ScoreBreakdown(_Persisted):
    """Every factor behind a scheduling decision, so a choice is explainable later."""

    root_impact: float = 0.0
    info_gain: float = 0.0
    resolve_chance: float = 0.0
    verifier_readiness: float = 0.0
    novelty: float = 0.0
    dependency_criticality: float = 0.0
    cost: float = 0.0
    redundancy: float = 0.0
    failure_risk: float = 0.0
    literature_boost: float = 0.0
    fairness: float = 0.0
    total: float = 0.0
    tie_break: str = ""


class WorkBudget(_Persisted):
    """What one work item may spend; ``max_steps`` = model turns."""

    max_steps: int
    max_tool_calls: int | None = None
    tokens_remaining: int | None = None
    cost_remaining_usd: float | None = None


class NormalizedProblem(_Persisted):
    problem_id: str
    statement: str
    target_scope: str = "unclear"
    assumptions: list[str] = Field(default_factory=list)
    definitions: list[str] = Field(default_factory=list)
    primary_claim_id: str | None = None
    title: str = ""


class ArtifactRef(_Persisted):
    """A pointer to a dossier/workspace artifact — never a copy of its status."""

    artifact_id: str
    kind: str
    branch_id: str | None = None
    work_item_id: str | None = None
    seq: int | None = None
    role: WorkerRole | None = None
    digest: str | None = None


class RoutingHint(_Persisted):
    required_capabilities: list[str] = Field(default_factory=list)


class ObligationProposal(_Persisted):
    statement: str
    assumptions: list[str] = Field(default_factory=list)
    quantifiers: list[str] = Field(default_factory=list)
    root_relation: RootRelation = RootRelation.unknown
    dependencies: list[str] = Field(default_factory=list)
    closure_modes: list[ClosureMode] = Field(default_factory=list)
    source_proof_id: str | None = None
    gap_marker: str | None = None
    supporting_artifacts: list[str] = Field(default_factory=list)


class ClosureProposal(_Persisted):
    """The verifier-coordinator's *proposal* to close an obligation with an artifact.

    A proposal names the accepted artifact, the closure mode it satisfies and the
    check that backed it; the engine turns it into ``obligation_closed``. Nothing here
    touches a claim status.
    """

    obligation_id: str
    artifact_id: str
    mode: ClosureMode
    check_id: str | None = None
    verdict: str = ""


class FailureSignature(_Persisted):
    signature_id: str
    key: str
    strategy_class: str
    target_obligation: str | None = None
    assumption_context: list[str] = Field(default_factory=list)
    tool_or_solver: str = ""
    error_category: ErrorCategory = "other"
    counterargument: str = ""
    artifact_ids: list[str] = Field(default_factory=list)
    branch_id: str | None = None
    work_item_id: str | None = None
    occurrences: int = 1
    first_seq: int | None = None
    last_seq: int | None = None
    retry_notes: list[str] = Field(default_factory=list)
    # The formal/certificate backends enabled when the failure was recorded, so a
    # ``verification_backend_changed`` reactivation condition has something to compare
    # against without re-reading an old config.
    verifier_backends: list[str] = Field(default_factory=list)


class Obligation(_Persisted):
    obligation_id: str
    campaign_id: str
    branch_id: str | None = None
    statement: str
    assumptions: list[str] = Field(default_factory=list)
    quantifiers: list[str] = Field(default_factory=list)
    root_relation: RootRelation = RootRelation.unknown
    dependencies: list[str] = Field(default_factory=list)
    closure_modes: list[ClosureMode] = Field(default_factory=list)
    status: ObligationStatus = ObligationStatus.open
    supporting_artifacts: list[str] = Field(default_factory=list)
    contradicting_artifacts: list[str] = Field(default_factory=list)
    failed_approaches: list[str] = Field(default_factory=list)
    review_findings: list[str] = Field(default_factory=list)
    closed_by_artifact: str | None = None
    closed_by_mode: ClosureMode | None = None
    closed_by_check: str | None = None
    created_seq: int = 0
    updated_seq: int = 0
    source_proof_id: str | None = None
    gap_marker: str | None = None


class WorkerContext(BaseModel):
    """The *only* thing a worker sees — frozen, ids and refs, no transcripts.

    Isolation is the point: a worker gets artifact *references* (restricted to
    verified/accepted ones), its own session id, its budget and its allowed tools;
    never another branch's session, never a chat transcript. A test asserts that no
    field of this model carries ``SessionMessage`` data.
    """

    model_config = ConfigDict(frozen=True)

    campaign_id: str
    branch_id: str | None
    work_item_id: str | None
    role: WorkerRole
    task_class: str
    mode: CampaignMode
    root_problem: NormalizedProblem
    branch_objective: str = ""
    strategy_summary: str = ""
    root_relation: RootRelation = RootRelation.unknown
    assumption_context: tuple[str, ...] = ()
    shared_artifacts: tuple[ArtifactRef, ...] = ()
    theorem_refs: tuple[str, ...] = ()
    failure_signatures: tuple[FailureSignature, ...] = ()
    open_obligations: tuple[Obligation, ...] = ()
    budget: WorkBudget = Field(default_factory=lambda: WorkBudget(max_steps=1))
    allowed_tools: frozenset[str] = frozenset()
    output_schema: dict[str, object] = Field(default_factory=dict)
    session_id: str = ""
    routing_hint: RoutingHint = Field(default_factory=RoutingHint)
    coverage_ref: str | None = None
    insufficient_categories: tuple[str, ...] = ()
    # Ids (never contents) of the artifacts this worker's own branch produced so far,
    # so a worker can tell "first attempt" from "continue" without reading transcripts.
    branch_artifact_ids: tuple[str, ...] = ()
    # The claim evidence is recorded against: the dossier's designated primary claim
    # when there is one, else the branch-level workspace claim the branch created.
    target_claim_id: str | None = None
    # Artifact ids the critic is asked to review (claims / proof attempts of this round).
    review_targets: tuple[str, ...] = ()
    # The branch's strategy template key (``proof_sketch``, ``counterexample_search``, …)
    # — the ``strategy_class`` of any failure signature the worker records.
    strategy_key: str | None = None

    @field_serializer("allowed_tools")
    def _sorted_tools(self, value: frozenset[str]) -> list[str]:
        return sorted(value)

    @field_validator("allowed_tools", mode="before")
    @classmethod
    def _to_frozenset(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(str(v) for v in value)
        return value


class WorkerResult(_Persisted):
    """What a worker hands back; the engine turns it into events (never statuses)."""

    status: WorkerResultStatus = "completed"
    artifacts_created: list[ArtifactRef] = Field(default_factory=list)
    proposed_nodes: list[CampaignNodeState] = Field(default_factory=list)
    obligations: list[ObligationProposal] = Field(default_factory=list)
    closure_proposals: list[ClosureProposal] = Field(default_factory=list)
    failure_signature: FailureSignature | None = None
    usage: CostTotals = Field(default_factory=CostTotals)
    routing_decision_id: str | None = None
    notes: list[str] = Field(default_factory=list)
    coverage_ref: str | None = None
    insufficient_categories: list[str] = Field(default_factory=list)
    error_category: ErrorCategory | None = None
    message: str = ""
    # The claim the worker recorded evidence against (the engine stores it on the branch).
    target_claim_id: str | None = None
    # Reviews the critic recorded and verifier-ledger entries a worker produced; the
    # engine turns them into ``review_recorded`` / ``verification_recorded`` events.
    reviews: list[ReviewRef] = Field(default_factory=list)
    verifications: list[VerificationRef] = Field(default_factory=list)


class WorkItem(_Persisted):
    work_item_id: str
    campaign_id: str
    branch_id: str
    role: WorkerRole
    task_class: str
    objective: str
    status: WorkItemStatus = WorkItemStatus.created
    attempt: int = 1
    created_seq: int = 0
    scheduled_seq: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    claimed_by: str | None = None
    score: ScoreBreakdown | None = None
    result_status: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    failure_signature_id: str | None = None
    routing_decision_id: str | None = None
    usage: CostTotals = Field(default_factory=CostTotals)
    session_id: str = ""
    failure_reason: str | None = None
    budget: WorkBudget | None = None


class BudgetLedger(_Persisted):
    """Spend vs. limits per axis; ``0`` limit = unlimited (mirrors the config).

    Unit of ``steps``: one model turn (``AgentLoop.steps_run``). A work item that
    makes no model call is charged one step so an offline campaign still terminates.
    ``exhausted`` lists the axes for which ``budget_exhausted`` was already emitted,
    so exhaustion is announced once per axis, not on every REALLOCATE pass.
    """

    steps_used: int = 0
    steps_limit: int = 0
    tokens_used: int = 0
    token_limit: int = 0
    cost_used_usd: float = 0.0
    cost_limit_usd: float = 0.0
    wall_seconds_used: float = 0.0
    wall_limit: int = 0
    per_branch: dict[str, CostTotals] = Field(default_factory=dict)
    per_work_item: dict[str, CostTotals] = Field(default_factory=dict)
    model_invocations: int = 0
    tool_executions: int = 0
    experiments_run: int = 0
    exhausted: list[str] = Field(default_factory=list)


class Diagnostic(_Persisted):
    kind: DiagnosticKind
    message: str
    seq: int | None = None
    line_no: int | None = None
    recorded_at: datetime | None = None


class CampaignNodeState(_Persisted):
    """A campaign-owned node of the (M5) proof tree: title + refs, never a claim status."""

    node_id: str
    kind: str
    title: str = ""
    statement: str = ""
    artifact_id: str | None = None
    branch_id: str | None = None
    work_item_id: str | None = None
    obligation_id: str | None = None
    root_relation: RootRelation = RootRelation.unknown
    status: str = "recorded"
    parents: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    created_seq: int = 0
    updated_seq: int = 0
    changes: list[str] = Field(default_factory=list)


class ReviewRef(_Persisted):
    review_id: str
    target_id: str
    kind: str = "review"
    verdict: str = ""
    seq: int | None = None


class VerificationRef(_Persisted):
    artifact_id: str
    backend: str = ""
    accepted: bool = False
    inconclusive: bool = False
    seq: int | None = None


class PhaseEntry(_Persisted):
    phase: CampaignPhase
    from_phase: CampaignPhase | None = None
    entered_seq: int
    entered_at: datetime
    reason: str = ""


class CurrentWorker(_Persisted):
    work_item_id: str
    branch_id: str
    role: WorkerRole
    session_id: str
    started_seq: int


class RouteSummary(_Persisted):
    decision_id: str
    task_class: str = ""
    selected_profile: str | None = None
    provider: str | None = None
    actual_model: str | None = None


class CampaignSnapshot(_Persisted):
    """The reducer's fold of the event log: orchestration state and references only.

    Deliberately absent: claim statuses, the root mathematical status, full coverage
    assessments, full routing records. Those are read from their own ledgers when a
    view needs them, so the snapshot can never disagree with the dossier.
    """

    schema_version: int = SCHEMA_VERSION
    campaign_id: str
    problem_id: str
    mode: CampaignMode
    phase: CampaignPhase = CampaignPhase.CREATED
    status: CampaignStatus = CampaignStatus.created
    resume_phase: CampaignPhase | None = None
    last_seq: int = 0
    last_event_id: str = ""
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    pause_reason: str | None = None
    stop_reason: str | None = None
    failure_reason: str | None = None
    completion_reason: str | None = None
    normalized_problem: NormalizedProblem | None = None
    branches: dict[str, BranchRecord] = Field(default_factory=dict)
    work_items: dict[str, WorkItem] = Field(default_factory=dict)
    obligations: dict[str, Obligation] = Field(default_factory=dict)
    failure_signatures: dict[str, FailureSignature] = Field(default_factory=dict)
    budget: BudgetLedger = Field(default_factory=BudgetLedger)
    routing_decision_ids: list[str] = Field(default_factory=list)
    last_route: RouteSummary | None = None
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    coverage_ref: str | None = None
    insufficient_categories: list[str] = Field(default_factory=list)
    campaign_nodes: dict[str, CampaignNodeState] = Field(default_factory=dict)
    reviews: list[ReviewRef] = Field(default_factory=list)
    verifications: list[VerificationRef] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    counters: dict[str, int] = Field(default_factory=dict)
    phase_history: list[PhaseEntry] = Field(default_factory=list)
    current_worker: CurrentWorker | None = None
    steps_executed: int = 0
    rounds: int = 0
    recent_event_ids: list[str] = Field(default_factory=list)


__all__ = [
    "SCHEMA_VERSION",
    "ArtifactRef",
    "BranchKind",
    "BranchRecord",
    "BranchStatus",
    "BudgetLedger",
    "BudgetScope",
    "CampaignConfigSnapshot",
    "CampaignMode",
    "CampaignNodeState",
    "CampaignPhase",
    "CampaignRecord",
    "CampaignSnapshot",
    "CampaignStatus",
    "ClosureMode",
    "ClosureProposal",
    "CostTotals",
    "CurrentWorker",
    "Diagnostic",
    "DiagnosticKind",
    "ErrorCategory",
    "FailureSignature",
    "NormalizedProblem",
    "Obligation",
    "ObligationProposal",
    "ObligationStatus",
    "PhaseEntry",
    "ReactivationCondition",
    "ReviewRef",
    "RootRelation",
    "RouteSummary",
    "RoutingHint",
    "ScoreBreakdown",
    "VerificationRef",
    "WorkBudget",
    "WorkItem",
    "WorkItemStatus",
    "WorkerContext",
    "WorkerResult",
    "WorkerResultStatus",
    "WorkerRole",
]
