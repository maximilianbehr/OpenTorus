"""OpenTorus CLI — graph commands (split from the former monolithic cli.py)."""

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

graph_app = typer.Typer(cls=SortedGroup, help="Inspect and edit the artifact relation graph.")
app.add_typer(graph_app, name="graph")


@graph_app.command("add")
def graph_add(
    source: str = typer.Argument(..., help="Source artifact id, e.g. EXP-0001."),
    target: str = typer.Argument(..., help="Target artifact id, e.g. CLAIM-0001."),
    relation: str = typer.Option(..., "--relation", help="Relation, e.g. tests, supports."),
    rationale: str = typer.Option("", "--rationale", help="Why this edge exists."),
) -> None:
    """Add a validated relation edge between two artifacts."""
    from opentorus.research.graph import add_edge

    base = _require_workspace_dir()
    try:
        edge = add_edge(base, source, target, relation, rationale)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{edge.id}[/green]: {edge.source_id} —{edge.relation}→ {edge.target_id}")


@graph_app.command("show")
def graph_show() -> None:
    """Show all edges in the artifact graph."""
    from opentorus.research.graph import list_edges

    base = _require_workspace_dir()
    edges = list_edges(base)
    if not edges:
        console.print("[dim]No edges yet.[/dim]")
        return
    table = Table(title="Artifact graph")
    table.add_column("ID", style="bold")
    table.add_column("Source")
    table.add_column("Relation")
    table.add_column("Target")
    for edge in edges:
        table.add_row(edge.id, edge.source_id, edge.relation, edge.target_id)
    console.print(table)


@graph_app.command("export")
def graph_export(
    fmt: str = typer.Option("mermaid", "--format", "-f", help="Output format: mermaid or ascii."),
    open_file: bool = typer.Option(
        False, "--open", help="Also write a standalone HTML/Mermaid file under .opentorus/."
    ),
    scope: str = typer.Option(
        "all", "--scope", help="Subgraph scope: all or literature (papers only)."
    ),
) -> None:
    """Export the artifact graph as a Mermaid or ASCII diagram."""
    from opentorus.research.graph import export_graph

    base = _require_workspace_dir()
    try:
        rendered = export_graph(base, fmt, open_file=open_file, scope=scope)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(rendered)


@graph_app.command("related")
def graph_related(
    artifact_id: str = typer.Argument(..., help="Artifact id to find relations for."),
) -> None:
    """Show edges touching a given artifact."""
    from opentorus.research.graph import related

    base = _require_workspace_dir()
    edges = related(base, artifact_id)
    if not edges:
        console.print(f"[dim]No relations for {artifact_id}.[/dim]")
        return
    for edge in edges:
        direction = "→" if edge.source_id == artifact_id else "←"
        other = edge.target_id if edge.source_id == artifact_id else edge.source_id
        console.print(f"  {edge.id}: {edge.relation} {direction} {other}")
