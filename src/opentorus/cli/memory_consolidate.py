"""OpenTorus CLI — ``memory consolidate`` / ``memory index`` (MEMORY.md and its usage)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape
from rich.table import Table

from opentorus.cli._base import _load_workspace_config, _require_workspace_dir, console
from opentorus.cli.memory import memory_app


def report_consolidation(result) -> None:  # noqa: ANN001 - ConsolidationResult
    """Print what a consolidation did (shared by the command and the end-of-run hook)."""
    for rec in result.summarized:
        label = rec.slug or rec.source
        note = f" ({rec.note})" if rec.note else ""
        console.print(f"[dim]{rec.id} {escape(rec.source)} -> {rec.status}{note} {label}[/dim]")
    record = result.record
    if record is None:
        return
    if record.status == "published":
        console.print(
            f"[green]MEMORY.md published[/green] ({record.id}): "
            f"{record.lines_before} -> {record.lines_after} entries"
            + (f", {len(record.dropped_unused)} aged out" if record.dropped_unused else "")
            + (
                f", {len(record.dropped_unsupported)} unsupported proof claim(s) removed"
                if record.dropped_unsupported
                else ""
            )
        )
    elif record.status == "rejected":
        console.print(
            f"[yellow]Consolidation rejected[/yellow] ({record.id}): {escape(record.reason)}. "
            "The previous MEMORY.md is unchanged."
        )
    else:
        console.print(f"[dim]MEMORY.md unchanged ({record.reason}).[/dim]")


def auto_consolidate(ot_dir: Path) -> None:
    """End-of-``run``/``campaign`` hook: consolidate when ``memory.auto_consolidate``."""
    from opentorus.memory_consolidation import maybe_auto_consolidate

    try:
        config = _load_workspace_config(ot_dir)
    except Exception:  # noqa: BLE001 — never fail a finished run over memory
        return
    result = maybe_auto_consolidate(ot_dir, config)
    if result is not None:
        report_consolidation(result)


@memory_app.command("consolidate")
def memory_consolidate(
    no_summarize: bool = typer.Option(
        False, "--no-summarize", help="Skip stage one; only merge already-written summaries."
    ),
) -> None:
    """Summarise new sessions/campaigns and rewrite .opentorus/MEMORY.md (validated)."""
    from opentorus.errors import OpenTorusError
    from opentorus.memory_consolidation import consolidate

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    try:
        result = consolidate(base, config, summarize=not no_summarize)
    except OpenTorusError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    report_consolidation(result)
    if result.record is not None and result.record.status == "rejected":
        raise typer.Exit(code=1)


@memory_app.command("index")
def memory_index() -> None:
    """Show MEMORY.md entries with their ids and citation-based retention state."""
    from datetime import UTC, datetime

    from opentorus.research.memory_index import is_expired, read_memory_lines, usage_stats

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    lines = read_memory_lines(base)
    if not lines:
        console.print("[dim]No MEMORY.md entries. Run `opentorus memory consolidate`.[/dim]")
        return
    stats = usage_stats(base)
    now = datetime.now(UTC)
    table = Table(title="MEMORY.md")
    table.add_column("ID", style="bold")
    table.add_column("Entry")
    table.add_column("Use", style="dim")
    for line in lines:
        usage = stats.get(line.entry_id)
        use = usage.describe() if usage else "not yet shown to any session"
        if is_expired(usage, now=now, max_unused_days=config.memory.max_unused_days):
            use += " (ages out at next consolidation)"
        table.add_row(line.entry_id, escape(line.text), use)
    console.print(table)
