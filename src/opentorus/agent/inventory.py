"""Compact research-artifact inventory for agent context and status."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

_MAX_SAMPLE = 3
_TITLE_LIMIT = 56
_GOAL_LIMIT = 72


def _short(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


class ArtifactInventory(BaseModel):
    num_papers: int = 0
    papers: list[str] = Field(default_factory=list)
    num_dossiers: int = 0
    dossiers: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    failed_tasks: list[str] = Field(default_factory=list)
    task_counts: dict[str, int] = Field(default_factory=dict)
    workspace_claims: int = 0
    experiments: int = 0
    experiment_lines: list[str] = Field(default_factory=list)
    hypotheses: int = 0
    has_python_project: bool = False
    script_paths: list[str] = Field(default_factory=list)


def _gather_script_hints(root: Path) -> list[str]:
    hints: list[str] = []
    for path in sorted(root.glob("*.py"))[:4]:
        if path.name.startswith("."):
            continue
        hints.append(path.name)
    for sub in ("scripts", "experiments"):
        folder = root / sub
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py"))[:4]:
            hints.append(f"{sub}/{path.name}")
    return hints[:8]


def gather_artifact_inventory(root: Path, ot_dir: Path) -> ArtifactInventory:
    """Collect a read-only summary of research artifacts (no directory walks)."""
    from opentorus.quality import workspace_has_quality_targets
    from opentorus.research.claims import list_claims
    from opentorus.research.dossier.store import list_dossiers
    from opentorus.research.experiments import list_experiments
    from opentorus.research.memory import list_memory
    from opentorus.research.papers import format_paper_agent_line, list_papers
    from opentorus.research.tasks import batch_task_summary, list_tasks

    papers = list_papers(ot_dir)
    dossiers = list_dossiers(ot_dir)
    tasks = list_tasks(ot_dir)

    paper_lines = [format_paper_agent_line(p, ot_dir) for p in papers[:_MAX_SAMPLE]]
    if len(papers) > _MAX_SAMPLE:
        paper_lines.append(f"… +{len(papers) - _MAX_SAMPLE} more (paper_list)")

    dossier_lines = [
        f"{d.id}: {_short(d.title or d.id, _TITLE_LIMIT)}" for d in dossiers[:_MAX_SAMPLE]
    ]
    if len(dossiers) > _MAX_SAMPLE:
        dossier_lines.append(f"… +{len(dossiers) - _MAX_SAMPLE} more")

    pending = [t for t in tasks if t.status in ("proposed", "in_progress")]
    failed = [t for t in tasks if t.status == "failed"]

    experiments = list_experiments(ot_dir)
    exp_lines = []
    for exp in experiments[-_MAX_SAMPLE:]:
        cmd = _short(exp.command or "python run.py", 40)
        exp_lines.append(f"{exp.id} [{exp.status}]: {cmd}")
    if len(experiments) > _MAX_SAMPLE:
        exp_lines.insert(0, f"… +{len(experiments) - _MAX_SAMPLE} older")

    def _task_line(task) -> str:
        return f"{task.id} ({task.category}): {_short(task.goal, _GOAL_LIMIT)}"

    return ArtifactInventory(
        num_papers=len(papers),
        papers=paper_lines,
        num_dossiers=len(dossiers),
        dossiers=dossier_lines,
        pending_tasks=[_task_line(t) for t in pending[:_MAX_SAMPLE]],
        failed_tasks=[_task_line(t) for t in failed[:_MAX_SAMPLE]],
        task_counts=batch_task_summary(ot_dir),
        workspace_claims=len(list_claims(ot_dir)),
        experiments=len(experiments),
        experiment_lines=exp_lines,
        hypotheses=len(list_memory(ot_dir, "hypotheses")),
        has_python_project=workspace_has_quality_targets(root),
        script_paths=_gather_script_hints(root),
    )


def format_artifact_inventory(
    inventory: ArtifactInventory,
    *,
    for_agent: bool = True,
) -> str:
    """Render inventory as text. ``for_agent`` adds tool-use hints."""
    if for_agent:
        header = (
            "Research artifacts (prefer status, paper_list, paper_read, memory_list — "
            "read_file on .opentorus/problems/PROBLEM-*/statement.md or project scripts; "
            "do not browse .opentorus/cache or run_shell opentorus …):"
        )
    else:
        header = "Research artifacts:"
    lines: list[str] = [header]

    if inventory.num_papers:
        lines.append(f"- papers ({inventory.num_papers}): " + "; ".join(inventory.papers))
    else:
        lines.append("- papers: none (paper_list, paper_fetch, paper_ingest_inbox)")

    if inventory.num_dossiers:
        lines.append(
            f"- problem dossiers ({inventory.num_dossiers}): " + "; ".join(inventory.dossiers)
        )
    else:
        lines.append("- problem dossiers: none (problem new / problem extract)")

    tc = inventory.task_counts
    if tc:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(tc.items()) if v)
        lines.append(f"- tasks: {parts}")
    else:
        lines.append("- tasks: none")
    if inventory.pending_tasks:
        lines.append("  pending: " + "; ".join(inventory.pending_tasks))
    if inventory.failed_tasks:
        lines.append("  failed: " + "; ".join(inventory.failed_tasks))

    lines.append(
        f"- workspace claims: {inventory.workspace_claims} | "
        f"experiments (EXP-*): {inventory.experiments} | "
        f"hypotheses in memory: {inventory.hypotheses}"
    )
    if inventory.experiment_lines:
        lines.append("  EXP: " + "; ".join(inventory.experiment_lines))
    if inventory.has_python_project:
        lines.append("- project code: Python project detected (quality gates apply)")
    else:
        lines.append(
            "- project code: no Python project in workspace root "
            "(paper/research workspace — quality gates skipped)"
        )
    if inventory.script_paths:
        lines.append("- scripts: " + ", ".join(inventory.script_paths))
    return "\n".join(lines)
