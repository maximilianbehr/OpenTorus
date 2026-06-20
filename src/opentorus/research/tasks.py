"""Research task pool and task cards.

Tasks are typed units of research/engineering work. The pool lives in
``.opentorus/tasks/TASK_POOL.json`` (a JSON list for easy human inspection) and
each task gets a Markdown card ``.opentorus/tasks/TASK-0001.md``. IDs are
deterministic (``TASK-0001``). Planning is delegated to ``agent.planner``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field

from opentorus.jsonl import next_sequential_id

TaskCategory = Literal["literature", "code", "experiment", "analysis", "review", "report"]
TaskStatus = Literal["proposed", "in_progress", "done", "blocked", "failed"]

# Statuses that still need work when resuming a plan.
_PENDING_STATUSES = ("proposed", "in_progress")

_VERIFICATION = {
    "literature": "Sources cited with local PAPER-* IDs; claims marked as evidence.",
    "code": "Changes are small and inspectable; tests run; diff shown.",
    "experiment": "Reproducible run with fixed seed; results stored under results/.",
    "analysis": "Observations separated from conclusions; limitations recorded.",
    "review": "Evidence and counterexamples examined before any status upgrade.",
    "report": "Report cites artifact IDs; framed as evidence, not final validation.",
}

_RESULT_CONTRACT = {
    "literature": "A list of relevant sources and observations.",
    "code": "A patch and a list of changed files.",
    "experiment": "An EXP-* entry with a summary of observed behavior.",
    "analysis": "A written analysis distinguishing evidence from conclusions.",
    "review": "A review note with limitations and recommended claim status.",
    "report": "Write analysis.md summarizing current artifacts.",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Task(BaseModel):
    id: str
    category: TaskCategory
    goal: str
    input_files: list[str] = Field(default_factory=list)
    allowed_scope: str = "workspace"
    verification_requirements: str = ""
    result_contract: str = ""
    status: TaskStatus = "proposed"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


def tasks_dir(ot_dir: Path) -> Path:
    return ot_dir / "tasks"


def _pool_path(ot_dir: Path) -> Path:
    return tasks_dir(ot_dir) / "TASK_POOL.json"


def list_tasks(ot_dir: Path) -> list[Task]:
    path = _pool_path(ot_dir)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Task.model_validate(item) for item in raw]


def _save_pool(ot_dir: Path, tasks: list[Task]) -> None:
    path = _pool_path(ot_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [task.model_dump(mode="json") for task in tasks]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _render_card(task: Task) -> str:
    return (
        f"# {task.id} — {task.category}\n\n"
        f"## Goal\n\n{task.goal}\n\n"
        "## Context\n\n_TODO_\n\n"
        "## Files likely involved\n\n"
        + ("\n".join(f"- {f}" for f in task.input_files) or "_None identified yet._")
        + "\n\n"
        "## Proposed steps\n\n_TODO_\n\n"
        "## Risks\n\n_TODO_\n\n"
        f"## Acceptance criteria\n\n{task.verification_requirements}\n\n"
        f"## Result contract\n\n{task.result_contract}\n\n"
        f"## Status\n\n{task.status}\n\n"
        "## Result\n\n_Not started._\n"
    )


def create_task(
    ot_dir: Path,
    category: TaskCategory,
    goal: str,
    input_files: list[str] | None = None,
) -> Task:
    existing = list_tasks(ot_dir)
    task_id = next_sequential_id("TASK", len(existing))
    task = Task(
        id=task_id,
        category=category,
        goal=goal,
        input_files=input_files or [],
        verification_requirements=_VERIFICATION[category],
        result_contract=_RESULT_CONTRACT[category],
    )
    existing.append(task)
    _save_pool(ot_dir, existing)
    (tasks_dir(ot_dir) / f"{task_id}.md").write_text(_render_card(task), encoding="utf-8")
    return task


def get_task(ot_dir: Path, task_id: str) -> Task | None:
    return next((t for t in list_tasks(ot_dir) if t.id == task_id), None)


def next_pending_task(
    ot_dir: Path,
    *,
    only_ids: set[str] | None = None,
    only_task_id: str | None = None,
) -> Task | None:
    """Return the first task that still needs work (proposed or in_progress).

    When ``only_ids`` is set, skip pending tasks outside that set (used by
    ``execute_plan`` to run only the batch just planned, not older backlog).
    When ``only_task_id`` is set, run only that task (``opentorus run --task``).
    """
    for task in list_tasks(ot_dir):
        if task.status not in _PENDING_STATUSES:
            continue
        if only_task_id is not None and task.id != only_task_id:
            continue
        if only_task_id is None and only_ids is not None and task.id not in only_ids:
            continue
        return task
    return None


def _filter_batch(tasks: list[Task], only_ids: set[str] | None) -> list[Task]:
    if only_ids is None:
        return tasks
    return [task for task in tasks if task.id in only_ids]


def reset_runnable_tasks(
    ot_dir: Path,
    *,
    only_ids: set[str] | None = None,
    include_failed: bool = True,
    include_in_progress: bool = True,
) -> list[str]:
    """Reset failed or stuck tasks to ``proposed`` so ``--resume`` can retry them."""
    reset_ids: list[str] = []
    for task in _filter_batch(list_tasks(ot_dir), only_ids):
        if task.status == "failed" and include_failed:
            set_task_status(ot_dir, task.id, "proposed")
            reset_ids.append(task.id)
        elif task.status == "in_progress" and include_in_progress:
            set_task_status(ot_dir, task.id, "proposed")
            reset_ids.append(task.id)
    return reset_ids


def batch_task_summary(ot_dir: Path, *, only_ids: set[str] | None = None) -> dict[str, int]:
    """Count tasks in a batch by status."""
    counts = {"proposed": 0, "in_progress": 0, "done": 0, "failed": 0, "blocked": 0}
    for task in _filter_batch(list_tasks(ot_dir), only_ids):
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts


def set_task_status(ot_dir: Path, task_id: str, status: TaskStatus) -> Task:
    """Update a task's status, persisting the pool and re-rendering its card."""
    from opentorus.errors import OpenTorusError

    tasks = list_tasks(ot_dir)
    for task in tasks:
        if task.id == task_id:
            task.status = status
            task.updated_at = _utcnow()
            _save_pool(ot_dir, tasks)
            (tasks_dir(ot_dir) / f"{task_id}.md").write_text(_render_card(task), encoding="utf-8")
            return task
    raise OpenTorusError(f"No task with id '{task_id}'.")


def clear_task_pool(ot_dir: Path) -> None:
    """Remove all tasks and task cards (for a fresh ``--plan`` run)."""
    td = tasks_dir(ot_dir)
    pool = _pool_path(ot_dir)
    if pool.is_file():
        pool.unlink()
    if td.is_dir():
        for card in td.glob("TASK-*.md"):
            card.unlink()


def plan_tasks(ot_dir: Path, goal: str, provider=None, *, use_llm: bool = True) -> list[Task]:
    """Plan a goal into tasks, persisting the pool and one card per task."""
    from opentorus.agent.planner import plan_with_provider

    specs = plan_with_provider(goal, provider, use_llm=use_llm)
    return [
        create_task(ot_dir, cast("TaskCategory", category), subgoal) for category, subgoal in specs
    ]
