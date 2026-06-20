"""Human-readable summaries after ``opentorus run`` / ``run --plan``."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.agent.task_validation import ArtifactSnapshot, snapshot_artifacts


class RunSummary(BaseModel):
    tool_calls: int = 0
    actions_ok: int = 0
    actions_failed: int = 0
    tasks_done: int = 0
    tasks_failed: int = 0
    delta: ArtifactSnapshot = Field(default_factory=ArtifactSnapshot)
    cost_usd: float = 0.0
    total_tokens: int = 0
    artifact_ids: list[str] = Field(default_factory=list)


def _action_counts(ot_dir: Path, *, since_action_id: str | None = None) -> tuple[int, int]:
    from opentorus.actions import list_actions

    entries = list_actions(ot_dir, limit=500)
    if since_action_id:
        ids = [e.id for e in entries]
        if since_action_id in ids:
            entries = entries[ids.index(since_action_id) + 1 :]
    ok = sum(1 for e in entries if e.ok)
    failed = sum(1 for e in entries if not e.ok)
    return ok, failed


def build_run_summary(
    root: Path,
    ot_dir: Path,
    *,
    before: ArtifactSnapshot,
    tool_calls: int = 0,
    since_action_id: str | None = None,
    tasks_done: int = 0,
    tasks_failed: int = 0,
) -> RunSummary:
    from opentorus.usage import summarize_usage

    after = snapshot_artifacts(root, ot_dir)
    usage = summarize_usage(ot_dir)
    ok, failed = _action_counts(ot_dir, since_action_id=since_action_id)
    delta = ArtifactSnapshot(
        papers=after.papers - before.papers,
        problems=after.problems - before.problems,
        claims=after.claims - before.claims,
        experiments=after.experiments - before.experiments,
        memory_entries=after.memory_entries - before.memory_entries,
        analysis_md=after.analysis_md and not before.analysis_md,
    )
    return RunSummary(
        tool_calls=tool_calls,
        actions_ok=ok,
        actions_failed=failed,
        tasks_done=tasks_done,
        tasks_failed=tasks_failed,
        delta=delta,
        cost_usd=usage.cost_usd,
        total_tokens=usage.total_tokens,
    )


def format_run_summary(summary: RunSummary) -> str:
    d = summary.delta
    parts = [
        f"Tool calls: {summary.tool_calls}",
        f"Actions: {summary.actions_ok} ok"
        + (f", {summary.actions_failed} failed" if summary.actions_failed else ""),
    ]
    if summary.tasks_done or summary.tasks_failed:
        parts.append(f"Tasks: {summary.tasks_done} done, {summary.tasks_failed} failed")
    deltas = []
    if d.papers:
        deltas.append(f"+{d.papers} paper(s)")
    if d.problems:
        deltas.append(f"+{d.problems} problem(s)")
    if d.claims:
        deltas.append(f"+{d.claims} claim(s)")
    if d.experiments:
        deltas.append(f"+{d.experiments} experiment(s)")
    if d.memory_entries:
        deltas.append(f"+{d.memory_entries} memory")
    if d.analysis_md:
        deltas.append("analysis.md created")
    if deltas:
        parts.append("Artifacts: " + ", ".join(deltas))
    parts.append(f"Usage: {summary.total_tokens} tokens, ${summary.cost_usd:.4f} (estimated)")
    return " | ".join(parts)
