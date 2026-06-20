"""OpenTorus CLI — journal commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _require_workspace_dir,
    app,
    console,
)

journal_app = typer.Typer(cls=SortedGroup, help="Inspect the autonomous-research journal.")
app.add_typer(journal_app, name="journal")


@journal_app.command("list")
def journal_list(
    query: str | None = typer.Option(None, "--search", "-q", help="Substring search."),
) -> None:
    """List (or search) research-journal entries."""
    from opentorus.research.journal import list_entries, search_entries

    base = _require_workspace_dir()
    entries = search_entries(base, query) if query else list_entries(base)
    if not entries:
        console.print("[dim]No journal entries.[/dim]")
        return
    table = Table(title="Research journal")
    table.add_column("ID", style="bold")
    table.add_column("Investigation")
    table.add_column("Iter")
    table.add_column("Claim")
    table.add_column("Next step")
    for e in entries:
        table.add_row(
            e.id,
            e.investigation,
            str(e.iteration),
            f"{e.claim_id or '—'} [{e.claim_status or '—'}]",
            (e.next_step[:60] + "…") if len(e.next_step) > 60 else e.next_step,
        )
    console.print(table)
