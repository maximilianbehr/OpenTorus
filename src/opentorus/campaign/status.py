"""``campaign status``: a summary of the orchestration state — and, separately, the
root mathematical status derived from dossier artifacts.

The two are shown side by side on purpose and labelled: *campaign status* is
phase/budget/branches (this layer's own state); *problem status* comes from
``problem verdict`` and the status gate and is never inferred from the campaign. A
completed campaign whose problem is still ``UNSOLVED`` is the normal case.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.campaign import events as ev
from opentorus.campaign.clock import Clock
from opentorus.campaign.facts import RootMathStatus, root_math_status
from opentorus.campaign.models import (
    BudgetLedger,
    CampaignMode,
    CampaignPhase,
    CampaignSnapshot,
    CampaignStatus,
    CurrentWorker,
    Diagnostic,
    ObligationStatus,
    RouteSummary,
)
from opentorus.campaign.store import CampaignStore, open_campaign

LATEST_EVENTS_SHOWN = 10


class EventLine(BaseModel):
    event_id: str
    type: str
    timestamp: datetime
    summary: str = ""


class CampaignStatusSummary(BaseModel):
    campaign_id: str
    problem_id: str
    mode: CampaignMode
    phase: CampaignPhase
    status: CampaignStatus
    resume_phase: CampaignPhase | None = None
    pause_reason: str | None = None
    stop_reason: str | None = None
    failure_reason: str | None = None
    completion_reason: str | None = None
    branch_counts: dict[str, int] = Field(default_factory=dict)
    obligations_open: int = 0
    obligations_closed: int = 0
    budget: BudgetLedger = Field(default_factory=BudgetLedger)
    latest_events: list[EventLine] = Field(default_factory=list)
    root_math_status: RootMathStatus = Field(default_factory=RootMathStatus)
    current_worker: CurrentWorker | None = None
    last_route: RouteSummary | None = None
    diagnostics_count: int = 0
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    coverage_ref: str | None = None
    insufficient_categories: list[str] = Field(default_factory=list)
    rounds: int = 0
    steps_executed: int = 0
    last_seq: int = 0
    artifact_count: int = 0
    created_at: datetime
    updated_at: datetime


def _summarize(event: ev.CampaignEvent) -> str:
    p = event.payload
    t = event.type
    if t in (ev.EventType.phase_entered,):
        return f"phase {p.get('phase')} (from {p.get('from_phase')})"
    if t == ev.EventType.phase_completed:
        return f"{p.get('phase')} -> {p.get('next_phase')}: {p.get('outcome', '')}"
    if t == ev.EventType.branch_proposed:
        return f"{p.get('branch_id')} {p.get('kind')}/{p.get('root_relation')}: {p.get('title')}"
    if t in (
        ev.EventType.branch_activated,
        ev.EventType.branch_completed,
        ev.EventType.branch_exhausted,
        ev.EventType.branch_rejected,
        ev.EventType.branch_suspended,
        ev.EventType.branch_reactivated,
    ):
        return str(p.get("branch_id", ""))
    if t == ev.EventType.work_item_created:
        return f"{p.get('work_item_id')} {p.get('role')} on {p.get('branch_id')}"
    if t in (
        ev.EventType.worker_started,
        ev.EventType.worker_completed,
        ev.EventType.worker_failed,
    ):
        return f"{p.get('work_item_id')} {p.get('status', p.get('message', ''))}".strip()
    if t == ev.EventType.artifact_created:
        return f"{p.get('artifact_id')} ({p.get('kind')})"
    if t == ev.EventType.theorem_reference_created:
        return (
            f"{p.get('theorem_reference_id')} ({p.get('paper_id') or 'paper ?'}, "
            f"{p.get('review_status', 'candidate')})"
        )
    if t == ev.EventType.budget_consumed:
        return f"{p.get('scope')} {p.get('ref')}: steps={p.get('steps')}"
    if t == ev.EventType.budget_exhausted:
        return f"{p.get('axis')} {p.get('used')}/{p.get('limit')}"
    if t in (
        ev.EventType.campaign_paused,
        ev.EventType.campaign_stopped,
        ev.EventType.campaign_failed,
    ):
        return str(p.get("reason", ""))
    if t == ev.EventType.campaign_completed:
        return f"{p.get('reason', '')} [{p.get('mode_criterion', '')}]"
    if t == ev.EventType.coverage_assessed:
        insufficient = p.get("insufficient")
        count = len(insufficient) if isinstance(insufficient, list) else 0
        return f"{p.get('coverage_ref')} insufficient={count}"
    if t == ev.EventType.obligation_closed:
        return f"{p.get('obligation_id')} by {p.get('artifact_id')} ({p.get('closure_mode')})"
    return ""


def summarize_snapshot(
    ot_dir: Path,
    snapshot: CampaignSnapshot,
    *,
    events: list[ev.CampaignEvent] | None = None,
    load_diagnostics: list[Diagnostic] | None = None,
) -> CampaignStatusSummary:
    """The summary for an already-loaded snapshot (the engine uses this after a run)."""
    counts: Counter[str] = Counter(b.status.value for b in snapshot.branches.values())
    latest = [
        EventLine(event_id=e.event_id, type=e.type, timestamp=e.timestamp, summary=_summarize(e))
        for e in (events or [])[-LATEST_EVENTS_SHOWN:]
    ]
    load_diags = list(load_diagnostics or [])
    diagnostics = [*load_diags, *snapshot.diagnostics]
    return CampaignStatusSummary(
        campaign_id=snapshot.campaign_id,
        problem_id=snapshot.problem_id,
        mode=snapshot.mode,
        phase=snapshot.phase,
        status=snapshot.status,
        resume_phase=snapshot.resume_phase,
        pause_reason=snapshot.pause_reason,
        stop_reason=snapshot.stop_reason,
        failure_reason=snapshot.failure_reason,
        completion_reason=snapshot.completion_reason,
        branch_counts=dict(sorted(counts.items())),
        obligations_open=sum(
            1
            for o in snapshot.obligations.values()
            if o.status in (ObligationStatus.open, ObligationStatus.in_progress)
        ),
        obligations_closed=sum(
            1 for o in snapshot.obligations.values() if o.status is ObligationStatus.closed
        ),
        budget=snapshot.budget,
        latest_events=latest,
        root_math_status=root_math_status(ot_dir, snapshot.problem_id),
        current_worker=snapshot.current_worker,
        last_route=snapshot.last_route,
        diagnostics_count=len(diagnostics),
        diagnostics=diagnostics,
        coverage_ref=snapshot.coverage_ref,
        insufficient_categories=list(snapshot.insufficient_categories),
        rounds=snapshot.rounds,
        steps_executed=snapshot.steps_executed,
        last_seq=snapshot.last_seq,
        artifact_count=len(snapshot.artifact_refs),
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


def build_status_summary(
    ot_dir: Path, campaign_id: str, *, clock: Clock | None = None
) -> CampaignStatusSummary:
    """Load ``campaign_id`` from disk and summarize it (read-only)."""
    store: CampaignStore = open_campaign(ot_dir, campaign_id, clock=clock)
    loaded = store.load()
    events, _read_diags = store.read_events()
    return summarize_snapshot(
        ot_dir, loaded.snapshot, events=events, load_diagnostics=loaded.diagnostics
    )


def _fmt_axis(used: float, limit: float, unit: str = "") -> str:
    lim = "unlimited" if limit <= 0 else f"{limit:g}{unit}"
    return f"{used:g}{unit} / {lim}"


def render_status(summary: CampaignStatusSummary) -> str:
    """Plain text (no Rich markup) for the CLI and for tests."""
    s = summary
    b = s.budget
    lines = [
        f"Campaign {s.campaign_id} on {s.problem_id}  mode={s.mode.value}",
        f"  campaign status: {s.status.value}  phase: {s.phase.value}"
        + (f"  resume-phase: {s.resume_phase.value}" if s.resume_phase else ""),
    ]
    if s.pause_reason:
        lines.append(f"  paused: {s.pause_reason}")
    if s.stop_reason:
        lines.append(f"  stopped: {s.stop_reason}")
    if s.failure_reason:
        lines.append(f"  failed: {s.failure_reason}")
    if s.completion_reason:
        lines.append(f"  completed: {s.completion_reason}")
    lines.append(
        "  budget: steps "
        + _fmt_axis(b.steps_used, b.steps_limit)
        + ", tokens "
        + _fmt_axis(b.tokens_used, b.token_limit)
        + ", cost "
        + _fmt_axis(b.cost_used_usd, b.cost_limit_usd, " USD")
        + ", wall "
        + _fmt_axis(b.wall_seconds_used, b.wall_limit, "s")
        + (f"  exhausted: {', '.join(b.exhausted)}" if b.exhausted else "")
    )
    branches = ", ".join(f"{k}={v}" for k, v in s.branch_counts.items()) or "none"
    lines.append(f"  branches: {branches}  rounds: {s.rounds}  artifacts: {s.artifact_count}")
    lines.append(f"  obligations: open={s.obligations_open} closed={s.obligations_closed}")
    if s.coverage_ref:
        lines.append(
            f"  coverage: {s.coverage_ref}  insufficient: "
            + (", ".join(s.insufficient_categories) or "none")
        )
    if s.current_worker:
        w = s.current_worker
        lines.append(f"  running: {w.work_item_id} ({w.role.value} on {w.branch_id})")
    if s.last_route:
        r = s.last_route
        lines.append(
            f"  last route: {r.decision_id} {r.task_class} -> {r.selected_profile or '?'}"
            + (f" ({r.actual_model})" if r.actual_model else "")
        )
    if s.diagnostics_count:
        lines.append(f"  diagnostics: {s.diagnostics_count} (see `campaign verify`)")
    root = s.root_math_status
    lines.append(
        "  problem status (derived from dossier artifacts, not from this campaign): "
        f"{root.label}; report status {root.report_status}"
    )
    lines.append(
        "  note: campaign status != problem status — a completed campaign does not mean "
        "the problem is solved; see `opentorus problem verdict`."
    )
    if s.latest_events:
        lines.append("  latest events:")
        for e in s.latest_events:
            lines.append(f"    {e.event_id} {e.type} {e.summary}".rstrip())
    return "\n".join(lines)


__all__ = [
    "LATEST_EVENTS_SHOWN",
    "CampaignStatusSummary",
    "EventLine",
    "build_status_summary",
    "render_status",
    "summarize_snapshot",
]
