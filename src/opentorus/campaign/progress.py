"""``progress.md``: the human-readable campaign progress file.

Its header sentence is the layer boundary in one line: campaign progress is
*orchestration* state; the mathematical status of the problem is derived from
dossier artifacts and shown separately. Written atomically; nothing reads it back.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.atomicio import atomic_write_text
from opentorus.campaign.clock import Clock
from opentorus.campaign.models import CampaignSnapshot
from opentorus.campaign.status import CampaignStatusSummary, build_status_summary
from opentorus.campaign.store import CampaignStore

HEADER_SENTENCE = (
    "Campaign progress is orchestration state (phase, budget, branches, work items); "
    "the mathematical status of the problem is derived from dossier artifacts and shown "
    "separately below — a completed campaign does not mean the problem is solved."
)


def render_progress_md(summary: CampaignStatusSummary, snapshot: CampaignSnapshot) -> str:
    s = summary
    b = s.budget
    lines = [
        f"# {s.campaign_id} — campaign progress",
        "",
        HEADER_SENTENCE,
        "",
        "## Orchestration state",
        "",
        f"- problem: {s.problem_id}",
        f"- mode: {s.mode.value}",
        f"- campaign status: {s.status.value}",
        f"- phase: {s.phase.value}"
        + (f" (resume: {s.resume_phase.value})" if s.resume_phase else ""),
        f"- rounds: {s.rounds}",
        f"- last event: {snapshot.last_event_id} (seq {snapshot.last_seq})",
    ]
    for label, value in (
        ("paused", s.pause_reason),
        ("stopped", s.stop_reason),
        ("failed", s.failure_reason),
        ("completed", s.completion_reason),
    ):
        if value:
            lines.append(f"- {label}: {value}")
    lines += [
        "",
        "## Budget",
        "",
        f"- steps: {b.steps_used} / {b.steps_limit or 'unlimited'}",
        f"- tokens: {b.tokens_used} / {b.token_limit or 'unlimited'}",
        f"- cost (USD): {b.cost_used_usd:g} / {b.cost_limit_usd or 'unlimited'}",
        f"- wall seconds: {b.wall_seconds_used:g} / {b.wall_limit or 'unlimited'}",
    ]
    if b.exhausted:
        lines.append(f"- exhausted axes: {', '.join(b.exhausted)}")
    lines += ["", "## Branches", ""]
    if snapshot.branches:
        for bid in sorted(snapshot.branches):
            br = snapshot.branches[bid]
            lines.append(
                f"- {bid} [{br.status.value}] {br.kind.value}/{br.root_relation.value} — "
                f"{br.title}: {br.objective} (worker {br.assigned_worker_role.value}, "
                f"{len(br.work_item_ids)} work item(s), steps {br.actual_cost.steps})"
            )
    else:
        lines.append("- (none yet)")
    lines += ["", "## Work items", ""]
    if snapshot.work_items:
        for wid in sorted(snapshot.work_items):
            wi = snapshot.work_items[wid]
            lines.append(
                f"- {wid} [{wi.status.value}] {wi.role.value} on {wi.branch_id}: "
                f"{wi.result_status or '-'}"
                + (f" — {wi.failure_reason}" if wi.failure_reason else "")
            )
    else:
        lines.append("- (none yet)")
    lines += ["", "## Obligations", ""]
    if snapshot.obligations:
        for oid in sorted(snapshot.obligations):
            ob = snapshot.obligations[oid]
            closed = (
                f" (closed by {ob.closed_by_artifact}, {ob.closed_by_mode})"
                if ob.closed_by_artifact
                else ""
            )
            lines.append(f"- {oid} [{ob.status.value}] {ob.statement}{closed}")
    else:
        lines.append("- (none)")
    lines += ["", "## Artifacts referenced", ""]
    if snapshot.artifact_refs:
        for ref in snapshot.artifact_refs:
            lines.append(
                f"- {ref.artifact_id} ({ref.kind})"
                + (f" via {ref.branch_id}" if ref.branch_id else "")
            )
    else:
        lines.append("- (none)")
    if s.coverage_ref:
        lines += [
            "",
            "## Literature coverage",
            "",
            f"- assessment: {s.coverage_ref}",
            "- insufficient critical categories: "
            + (", ".join(s.insufficient_categories) or "none"),
        ]
    r = s.root_math_status
    lines += [
        "",
        "## Problem status (derived from dossier artifacts)",
        "",
        f"- classification: {r.label}",
        f"- rationale: {r.rationale}",
        f"- report status: {r.report_status} — {r.report_rationale}",
        f"- primary claim: {r.primary_claim_id or '(none designated)'}",
        f"- target scope: {r.target_scope}",
        "",
        "Run `opentorus problem verdict` for the authoritative derivation.",
    ]
    if s.diagnostics_count:
        lines += ["", "## Diagnostics", ""]
        for d in s.diagnostics:
            lines.append(f"- {d.kind}: {d.message}")
    return "\n".join(lines) + "\n"


def write_progress(
    store: CampaignStore, summary: CampaignStatusSummary, snapshot: CampaignSnapshot | None = None
) -> Path:
    """Write the store's ``progress.md`` (from its current snapshot unless one is given)."""
    path = store.progress_path
    atomic_write_text(path, render_progress_md(summary, snapshot or store.snapshot))
    return path


def write_progress_for(ot_dir: Path, campaign_id: str, *, clock: Clock | None = None) -> Path:
    """Load the campaign from disk, summarize it and write ``progress.md``."""
    from opentorus.campaign.store import open_campaign

    store = open_campaign(ot_dir, campaign_id, clock=clock)
    loaded = store.load()
    summary = build_status_summary(ot_dir, campaign_id, clock=clock)
    return write_progress(store, summary, loaded.snapshot)


__all__ = ["HEADER_SENTENCE", "render_progress_md", "write_progress", "write_progress_for"]
