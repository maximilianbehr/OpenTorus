"""OpenTorus CLI — memory commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.research.memory import VALID_KINDS, add_memory, list_memory

# Map user-facing (often singular) kind names to canonical memory ledgers.
_KIND_ALIASES = {
    "fact": "facts",
    "decision": "decisions",
    "failed_attempt": "failed_attempts",
    "failed": "failed_attempts",
    "hypothesis": "hypotheses",
    "observation": "observations",
}


def _normalize_kind(kind: str) -> str:
    canonical = _KIND_ALIASES.get(kind, kind)
    if canonical not in VALID_KINDS:
        valid = ", ".join(VALID_KINDS)
        console.print(f"[red]Unknown memory kind '{kind}'.[/red] Valid kinds: {valid}.")
        raise typer.Exit(code=1)
    return canonical


memory_app = typer.Typer(cls=SortedGroup, help="Manage structured project memory.")
app.add_typer(memory_app, name="memory")


@memory_app.command("add")
def memory_add(
    text: str = typer.Argument(..., help="The memory text to store."),
    kind: str = typer.Option("fact", "--kind", help="Memory kind (fact, decision, ...)."),
) -> None:
    """Append a memory entry of the given kind."""
    base = _require_workspace_dir()
    entry = add_memory(base, _normalize_kind(kind), text)  # type: ignore[arg-type]
    console.print(f"[green]{entry.id}[/green] ({entry.kind}): {entry.text}")


@memory_app.command("list")
def memory_list(
    kind: str = typer.Option("fact", "--kind", help="Memory kind to list."),
) -> None:
    """List memory entries of the given kind."""
    base = _require_workspace_dir()
    entries = list_memory(base, _normalize_kind(kind))  # type: ignore[arg-type]
    canonical = _normalize_kind(kind)
    if not entries:
        console.print(f"[dim]No memory entries of kind '{canonical}'.[/dim]")
        return
    table = Table(title=f"Memory: {canonical}")
    table.add_column("ID", style="bold")
    table.add_column("Text")
    table.add_column("Created", style="dim")
    for entry in entries:
        table.add_row(entry.id, entry.text, entry.created_at.isoformat())
    console.print(table)
