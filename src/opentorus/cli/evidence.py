"""OpenTorus CLI — evidence commands (split from the former monolithic cli.py)."""

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

evidence_app = typer.Typer(cls=SortedGroup, help="Track evidence linked to claims (not truth).")
app.add_typer(evidence_app, name="evidence")


@evidence_app.command("add")
def evidence_add(
    claim_id: str = typer.Argument(..., help="Claim id this evidence concerns."),
    source: str | None = typer.Option(None, "--source", help="Source artifact id, e.g. EXP-0002."),
    source_type: str = typer.Option(
        "experiment", "--type", help="experiment/paper/log/code/user_review/external/manual_note."
    ),
    direction: str = typer.Option(
        "supports", "--direction", help="supports/contradicts/mixed/neutral."
    ),
    strength: str = typer.Option("moderate", "--strength", help="weak/moderate/strong."),
    summary: str = typer.Option("", "--summary", help="What the evidence shows."),
) -> None:
    """Add an evidence record for a claim (never auto-upgrades the claim)."""
    from opentorus.research.dossier.store import get_active_problem
    from opentorus.research.evidence import add_evidence

    base = _require_workspace_dir()
    try:
        ev, advisory = add_evidence(
            base,
            claim_id,
            source_type=source_type,
            source_id=source,
            summary=summary,
            direction=direction,
            strength=strength,
            problem_id=get_active_problem(base),
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{ev.id}[/green] added for {claim_id} [{ev.direction}/{ev.strength}].")
    if advisory:
        console.print(f"[yellow]{advisory}[/yellow]")


@evidence_app.command("list")
def evidence_list(
    claim_id: str = typer.Argument(..., help="Claim id to list evidence for."),
) -> None:
    """List evidence linked to a claim."""
    from opentorus.research.evidence import list_evidence

    base = _require_workspace_dir()
    entries = list_evidence(base, claim_id)
    if not entries:
        console.print(f"[dim]No evidence for {claim_id}.[/dim]")
        return
    table = Table(title=f"Evidence for {claim_id}")
    table.add_column("ID", style="bold")
    table.add_column("Direction")
    table.add_column("Strength")
    table.add_column("Source")
    table.add_column("Summary")
    for ev in entries:
        source = f"{ev.source_type}:{ev.source_id}" if ev.source_id else ev.source_type
        table.add_row(ev.id, ev.direction, ev.strength, source, ev.summary)
    console.print(table)


@evidence_app.command("show")
def evidence_show(
    evidence_id: str = typer.Argument(..., help="Evidence id, e.g. EVIDENCE-0001."),
) -> None:
    """Show a single evidence record in detail."""
    from opentorus.research.evidence import get_evidence

    base = _require_workspace_dir()
    ev = get_evidence(base, evidence_id)
    if ev is None:
        console.print(f"[red]No evidence with id '{evidence_id}'.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{ev.id}[/bold]")
    console.print(f"Claim: {ev.claim_id}")
    console.print(f"Source: {ev.source_type}" + (f":{ev.source_id}" if ev.source_id else ""))
    console.print(f"Direction: {ev.direction}")
    console.print(f"Strength: {ev.strength}")
    console.print(f"Summary: {ev.summary or '(none)'}")
    console.print(f"Limitations: {', '.join(ev.limitations) or '(none)'}")
