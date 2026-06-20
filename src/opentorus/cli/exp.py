"""OpenTorus CLI — exp commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.errors import OpenTorusError

exp_app = typer.Typer(cls=SortedGroup, help="Manage reproducible experiments.")
app.add_typer(exp_app, name="exp")


@exp_app.command("new")
def exp_new(
    title: str = typer.Argument(..., help="Experiment title."),
    template: str = typer.Option(
        "default",
        "--template",
        "-t",
        help="default | symbolic | numerical | counterexample_search | validated_numerics.",
    ),
    environment: str | None = typer.Option(
        None, "--environment", "-e", help="Named tool environment (e.g. julia, cpp)."
    ),
    command: str | None = typer.Option(
        None,
        "--command",
        "-c",
        help="Command to run (e.g. python scripts/foo.py --all). Runs from workspace root.",
    ),
    run_from: str = typer.Option(
        "experiment",
        "--run-from",
        help="experiment (default) or workspace — use workspace for scripts/ paths.",
    ),
) -> None:
    """Create a new experiment folder with a safe run.py template."""
    from opentorus.research.experiments import new_experiment

    base = _require_workspace_dir()
    if run_from not in ("experiment", "workspace"):
        console.print("[red]--run-from must be 'experiment' or 'workspace'.[/red]")
        raise typer.Exit(code=1)
    try:
        experiment = new_experiment(
            base,
            title,
            template=template,
            environment=environment,
            command=command,
            run_from=run_from,  # type: ignore[arg-type]
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    suffix = f" [env: {experiment.environment}]" if experiment.environment else ""
    console.print(f"[green]{experiment.id}[/green] created at .opentorus/{experiment.path}{suffix}")


@exp_app.command("list")
def exp_list() -> None:
    """List experiments."""
    from opentorus.research.experiments import list_experiments

    base = _require_workspace_dir()
    experiments = list_experiments(base)
    if not experiments:
        console.print("[dim]No experiments yet.[/dim]")
        return
    table = Table(title="Experiments")
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Title")
    for experiment in experiments:
        table.add_row(experiment.id, experiment.status, experiment.title)
    console.print(table)


@exp_app.command("run")
def exp_run(exp_id: str = typer.Argument(..., help="Experiment id, e.g. EXP-0001.")) -> None:
    """Run an experiment locally and capture its logs."""
    from opentorus.research.experiments import run_experiment

    base = _require_workspace_dir()
    console.print(f"[bold]●[/bold] Running {exp_id}")
    try:
        experiment, exit_code = run_experiment(base, exp_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    label = "completed" if exit_code == 0 else f"failed (exit {exit_code})"
    color = "green" if exit_code == 0 else "red"
    console.print(f"[dim]⎿ {experiment.command} → [{color}]{label}[/{color}][/dim]")
    console.print("This is evidence, not final validation.")


@exp_app.command("replay")
def exp_replay(exp_id: str = typer.Argument(..., help="Experiment id, e.g. EXP-0001.")) -> None:
    """Re-run a recorded experiment and report any divergence from its manifest."""
    from opentorus.research.repro import replay_experiment

    base = _require_workspace_dir()
    console.print(f"[bold]●[/bold] Replaying {exp_id}")
    try:
        report = replay_experiment(base, exp_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if report.reproducible:
        console.print("[green]Reproducible:[/green] replay matches the recorded run.")
    else:
        console.print("[yellow]Divergence detected[/yellow] (reported as evidence):")
        for note in report.divergences:
            console.print(f"  - {note}")
        if report.stdout_diff:
            console.print(report.stdout_diff)
    console.print("This is evidence about reproducibility, not a pass/fail verdict.")


@exp_app.command("summarize")
def exp_summarize(exp_id: str = typer.Argument(..., help="Experiment id, e.g. EXP-0001.")) -> None:
    """Generate a structured summary.md from an experiment's results."""
    from opentorus.research.experiments import summarize_experiment

    base = _require_workspace_dir()
    try:
        experiment = summarize_experiment(base, exp_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]{experiment.id}[/green] summary written to .opentorus/{experiment.path}/summary.md"
    )
    console.print("This is evidence, not final validation.")
