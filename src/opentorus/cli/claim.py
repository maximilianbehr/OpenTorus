"""OpenTorus CLI — claim commands (split from the former monolithic cli.py)."""

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

claim_app = typer.Typer(cls=SortedGroup, help="Manage research claims.")
app.add_typer(claim_app, name="claim")


@claim_app.command("new")
def claim_new(statement: str = typer.Argument(..., help="The claim statement.")) -> None:
    """Create a new claim (status: idea)."""
    from opentorus.research.claims import new_claim

    base = _require_workspace_dir()
    claim = new_claim(base, statement)
    console.print(f"[green]{claim.id}[/green] ({claim.status}): {claim.statement}")


@claim_app.command("list")
def claim_list() -> None:
    """List all claims."""
    from opentorus.research.claims import list_claims

    base = _require_workspace_dir()
    claims = list_claims(base)
    if not claims:
        console.print("[dim]No claims yet.[/dim]")
        return
    table = Table(title="Claims")
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Statement")
    table.add_column("Updated", style="dim")
    for claim in claims:
        statement = claim.statement if len(claim.statement) <= 60 else claim.statement[:57] + "..."
        table.add_row(claim.id, claim.status, statement, claim.updated_at.date().isoformat())
    console.print(table)


@claim_app.command("show")
def claim_show(claim_id: str = typer.Argument(..., help="Claim id, e.g. CLAIM-0001.")) -> None:
    """Show a single claim in detail."""
    from opentorus.research.claims import get_claim

    base = _require_workspace_dir()
    claim = get_claim(base, claim_id)
    if claim is None:
        console.print(f"[red]No claim with id '{claim_id}'.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{claim.id}[/bold]")
    console.print(f"Statement: {claim.statement}")
    console.print(f"Status: {claim.status}")
    console.print(f"Allowed usage: {claim.allowed_usage}")
    console.print(f"Support: {', '.join(claim.support) or '(none)'}")
    console.print(f"Dependencies: {', '.join(claim.dependencies) or '(none)'}")
    console.print(f"Counterexamples: {', '.join(claim.counterexamples) or '(none)'}")
    console.print(f"Limitations: {', '.join(claim.limitations) or '(none)'}")

    from opentorus.research.evidence import list_evidence

    evidence = list_evidence(base, claim_id)
    if evidence:
        console.print("\n[bold]Linked evidence:[/bold]")
        for ev in evidence:
            source = f":{ev.source_id}" if ev.source_id else ""
            console.print(
                f"  {ev.id} [{ev.direction}/{ev.strength}] ({ev.source_type}{source}) {ev.summary}"
            )
    else:
        console.print("\nLinked evidence: (none)")


@claim_app.command("update")
def claim_update(
    claim_id: str = typer.Argument(..., help="Claim id, e.g. CLAIM-0001."),
    status: str | None = typer.Option(None, "--status", help="New claim status."),
    support: str | None = typer.Option(None, "--support", help="Add a support artifact id."),
) -> None:
    """Update a claim's status or support (restricted upgrades require confirmation)."""
    from opentorus.research.claims import update_claim

    base = _require_workspace_dir()
    config = _load_workspace_config(base)

    if status in {"verified", "formally_verified"} and config.agent.mode == "review":
        from opentorus.permissions.policy import evaluate_claim_verification

        decision = evaluate_claim_verification(review=True)
        console.print(f"[red]Blocked:[/red] {decision.reason}")
        raise typer.Exit(code=1)

    def _confirm(current: str, new: str) -> bool:
        console.print(
            f"\n[yellow]Restricted upgrade:[/yellow] {current} → {new}.\n"
            "This should only happen after explicit human review."
        )
        return console.input("Confirm upgrade? [y] yes  [n] no: ").strip().lower() in {"y", "yes"}

    try:
        claim = update_claim(
            base,
            claim_id,
            status=status,  # type: ignore[arg-type]
            add_support=support,
            confirm=_confirm,
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{claim.id}[/green] is now [bold]{claim.status}[/bold].")
