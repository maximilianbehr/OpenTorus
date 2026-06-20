"""OpenTorus CLI — review commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _load_workspace_config,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.errors import OpenTorusError

review_app = typer.Typer(cls=SortedGroup, help="Adversarial review: challenge, record, and gate.")
app.add_typer(review_app, name="review")


@review_app.command("run")
def review_run(
    target_id: str = typer.Argument(..., help="Artifact id (CLAIM-*/EXP-*)."),
) -> None:
    """Run the critic against an artifact and record findings."""
    from opentorus.agent.review import review_target

    base = _require_workspace_dir()
    try:
        review = review_target(base, target_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    color = {"pass": "green", "revise": "yellow", "block": "red"}[review.verdict]
    console.print(f"[{color}]{review.id}: {review.verdict}[/{color}] for {target_id}.")
    for f in review.findings:
        console.print(f"  [{f.severity}] ({f.category}) {f.finding_id}: {f.rationale}")


@review_app.command("list")
def review_list() -> None:
    """List recorded reviews."""
    from opentorus.agent.review import list_reviews

    base = _require_workspace_dir()
    reviews = list_reviews(base)
    if not reviews:
        console.print("[dim]No reviews yet.[/dim]")
        return
    table = Table(title="Reviews")
    table.add_column("ID", style="bold")
    table.add_column("Target")
    table.add_column("Verdict")
    table.add_column("Findings")
    for r in reviews:
        table.add_row(r.id, r.target_id, r.verdict, str(len(r.findings)))
    console.print(table)


@review_app.command("resolve")
def review_resolve(
    review_id: str = typer.Argument(..., help="Review id, e.g. REVIEW-0001."),
    finding_id: str = typer.Argument(..., help="Finding id, e.g. REVIEW-0001-F1."),
    resolution: str = typer.Argument(..., help="accepted | disputed | deferred."),
    note: str = typer.Option("", "--note", help="Resolution rationale."),
) -> None:
    """Resolve a finding (accepted/disputed/deferred) to clear the gate."""
    from opentorus.agent.review import resolve_finding

    base = _require_workspace_dir()
    try:
        resolve_finding(base, review_id, finding_id, resolution, note)  # type: ignore[arg-type]
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{finding_id}[/green] → {resolution}.")


@review_app.command("gate")
def review_gate(target_id: str = typer.Argument(..., help="Artifact id to check.")) -> None:
    """Check whether an artifact may be published given open blocking findings."""
    from opentorus.agent.review import gate_publication

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    review_mode = config.agent.mode == "review"
    decision = gate_publication(base, target_id, review_mode=review_mode)
    color = "green" if decision.allowed else "red"
    label = "allowed" if decision.allowed else "blocked"
    console.print(f"[{color}]{label}[/{color}]: {decision.reason}")
    for f in decision.blocking:
        console.print(f"  [blocking] {f.finding_id}: {f.rationale}")
