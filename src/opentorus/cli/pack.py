"""OpenTorus CLI — pack commands (split from the former monolithic cli.py)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.errors import OpenTorusError

pack_app = typer.Typer(cls=SortedGroup, help="Share and reproduce a whole investigation.")
app.add_typer(pack_app, name="pack")


@pack_app.command("export")
def pack_export(
    out: str | None = typer.Option(None, "--out", help="Output .zip path."),
) -> None:
    """Bundle the investigation into a privacy/license-clean reviewer pack."""
    from opentorus.research.pack import export_pack

    base = _require_workspace_dir()
    path = export_pack(base, Path(out) if out else None)
    console.print(f"[green]Research pack[/green] written to {path}")


@pack_app.command("reproduce")
def pack_reproduce() -> None:
    """Re-run recorded experiments and flag any reproducibility mismatch."""
    from opentorus.research.pack import reproduce_pack

    base = _require_workspace_dir()
    reports = reproduce_pack(base)
    if not reports:
        console.print("[dim]No experiments with a recorded baseline to reproduce.[/dim]")
        return
    table = Table(title="Reproducibility")
    table.add_column("Experiment", style="bold")
    table.add_column("Reproducible")
    table.add_column("Divergences")
    for r in reports:
        ok = "[green]yes[/green]" if r.reproducible else "[red]no[/red]"
        table.add_row(r.experiment_id, ok, "; ".join(r.divergences) or "—")
    console.print(table)


@pack_app.command("notebook")
def pack_notebook(
    exp_id: str = typer.Argument(..., help="Experiment id, e.g. EXP-0001."),
) -> None:
    """Export a single experiment as a Jupyter notebook."""
    from opentorus.research.pack import export_experiment_notebook

    base = _require_workspace_dir()
    try:
        path = export_experiment_notebook(base, exp_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Notebook[/green] written to {path}")
