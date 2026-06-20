"""OpenTorus CLI — task commands (split from the former monolithic cli.py)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.errors import OpenTorusError

task_app = typer.Typer(cls=SortedGroup, help="Plan and track research tasks.")
app.add_typer(task_app, name="task")


@task_app.command("plan")
def task_plan(goal: str = typer.Argument(..., help="The goal to plan into tasks.")) -> None:
    """Decompose a goal into typed tasks with task cards."""
    from opentorus.research.tasks import plan_tasks

    base = _require_workspace_dir()
    tasks = plan_tasks(base, goal)
    console.print(f"[green]Planned {len(tasks)} task(s).[/green]")
    table = Table(title="Planned tasks")
    table.add_column("ID", style="bold")
    table.add_column("Category")
    table.add_column("Goal")
    for task in tasks:
        table.add_row(task.id, task.category, task.goal)
    console.print(table)


@task_app.command("list")
def task_list() -> None:
    """List tasks in the pool."""
    from opentorus.research.tasks import list_tasks

    base = _require_workspace_dir()
    tasks = list_tasks(base)
    if not tasks:
        console.print("[dim]No tasks yet.[/dim]")
        return
    table = Table(title="Tasks")
    table.add_column("ID", style="bold")
    table.add_column("Category")
    table.add_column("Status")
    table.add_column("Goal")
    for task in tasks:
        table.add_row(task.id, task.category, task.status, task.goal)
    console.print(table)


@task_app.command("retry")
def task_retry(
    task_id: Annotated[
        list[str] | None,
        typer.Argument(help="Task id(s) to reset (omit for all failed in the last batch)."),
    ] = None,
) -> None:
    """Reset failed or stuck tasks to proposed so ``run --resume`` can retry them."""
    from opentorus.agent.run_state import load_run_state
    from opentorus.research.tasks import list_tasks, reset_runnable_tasks, set_task_status

    ot_dir = _require_workspace_dir()
    ids = task_id or []
    only_ids: set[str] | None = set(ids) if ids else None
    if only_ids is None:
        state = load_run_state(ot_dir)
        if state and state.batch_task_ids:
            only_ids = set(state.batch_task_ids)
    if only_ids is not None:
        reset = reset_runnable_tasks(ot_dir, only_ids=only_ids)
    else:
        reset = []
        for task in list_tasks(ot_dir):
            if task.status in ("failed", "in_progress"):
                set_task_status(ot_dir, task.id, "proposed")
                reset.append(task.id)
    if not reset:
        console.print("[dim]No failed or in-progress tasks to retry.[/dim]")
        return
    console.print(f"[green]Reset {len(reset)} task(s) to proposed:[/green] {', '.join(reset)}")
    console.print("[dim]Run `opentorus run --resume` to execute them.[/dim]")


@task_app.command("done")
def task_done(
    task_id: str = typer.Argument(..., help="Task id to mark done, e.g. TASK-0004."),
) -> None:
    """Mark a task as done (e.g. when deliverables were produced outside ``run --plan``)."""
    from opentorus.research.tasks import set_task_status

    ot_dir = _require_workspace_dir()
    try:
        task = set_task_status(ot_dir, task_id, "done")
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{task.id}[/green] marked done ({task.category}).")
