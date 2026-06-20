"""OpenTorus CLI — index commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer

from opentorus.cli._base import (
    SortedGroup,
    _load_workspace_config,
    _require_workspace_dir,
    app,
    console,
)

index_app = typer.Typer(cls=SortedGroup, help="Build and query the local artifact index.")
app.add_typer(index_app, name="index")


@index_app.command("build")
def index_build() -> None:
    """(Re)build the artifact index from memory, claims, papers, reports, experiments."""
    from opentorus.research.embeddings import load_embedder
    from opentorus.research.index import build_index

    ot_dir = _require_workspace_dir()
    config = _load_workspace_config(ot_dir)
    embedder = load_embedder(config)
    status = build_index(ot_dir, embedder=embedder)
    by_type = ", ".join(f"{t}={n}" for t, n in status.by_type.items()) or "none"
    mode = f"hybrid ({status.embeddings_model})" if status.embeddings else "BM25-only"
    console.print(f"[green]Indexed {status.count} document(s) [{mode}].[/green] {by_type}")


@index_app.command("status")
def index_status_cmd() -> None:
    """Show whether the index is built and what it contains."""
    from opentorus.research.index import index_status

    ot_dir = _require_workspace_dir()
    status = index_status(ot_dir)
    if not status.built:
        console.print("Index not built yet. Run `opentorus index build`.")
        return
    by_type = "\n".join(f"  {t}: {n}" for t, n in status.by_type.items())
    console.print(f"Index built at {status.built_at} — {status.count} document(s):\n{by_type}")


@index_app.command("search")
def index_search(
    query: str = typer.Argument(..., help="Search query."),
    k: int = typer.Option(5, "--limit", "-k", help="Maximum results."),
) -> None:
    """Search the index and show the most relevant artifacts."""
    from opentorus.research.embeddings import load_embedder
    from opentorus.research.index import hybrid_search

    ot_dir = _require_workspace_dir()
    config = _load_workspace_config(ot_dir)
    embedder = load_embedder(config)
    results = hybrid_search(ot_dir, query, k=k, embedder=embedder)
    if not results:
        console.print("No matching artifacts.")
        return
    for doc, score in results:
        console.print(
            f"[green]{doc.artifact_id}[/green] ({doc.artifact_type}, {score:.2f}): {doc.title}"
        )
