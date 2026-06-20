"""OpenTorus CLI — kb commands (split from the former monolithic cli.py)."""

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

kb_app = typer.Typer(cls=SortedGroup, help="Cross-workspace knowledge base (promote, query).")
app.add_typer(kb_app, name="kb")


@kb_app.command("promote")
def kb_promote(
    paper_id: str = typer.Argument(..., help="Paper id to promote, e.g. PAPER-0001."),
) -> None:
    """Promote a workspace paper (and its note) into the user-level knowledge base."""
    from opentorus.research.kb import promote_citations, promote_paper

    base = _require_workspace_dir()
    try:
        entry, created = promote_paper(base, paper_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    promote_citations(base)
    state = "promoted" if created else "already present (deduped)"
    console.print(f"[green]{entry.id}[/green] {state}: {entry.title or entry.doi or paper_id}")


@kb_app.command("query")
def kb_query(
    query: str = typer.Argument(..., help="Search the knowledge base."),
    limit: int = typer.Option(5, "--limit", "-k", help="Max results."),
) -> None:
    """Search the cross-workspace knowledge base (BM25)."""
    from opentorus.research.kb import query_kb

    hits = query_kb(query, k=limit)
    if not hits:
        console.print("[dim]No knowledge-base matches.[/dim]")
        return
    table = Table(title=f"Knowledge base: {query}")
    table.add_column("ID", style="bold")
    table.add_column("Score")
    table.add_column("Title")
    table.add_column("Origin", style="dim")
    for entry, score in hits:
        table.add_row(
            entry.id,
            f"{score:.2f}",
            (entry.title or entry.doi or "")[:50],
            entry.origin_workspace or "",
        )
    console.print(table)


@kb_app.command("stale")
def kb_stale(
    days: int = typer.Option(90, "--days", help="Staleness window in days."),
) -> None:
    """List knowledge-base entries due for re-verification."""
    from opentorus.research.kb import stale_entries

    entries = stale_entries(staleness_days=days)
    if not entries:
        console.print(f"[green]No entries older than {days} days.[/green]")
        return
    for entry in entries:
        console.print(
            f"- {entry.id}: {entry.title or entry.doi} (last checked {entry.last_checked.date()})"
        )
