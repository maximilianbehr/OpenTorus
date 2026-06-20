"""OpenTorus CLI — data commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _build_egress_guard,
    _load_workspace_config,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.errors import OpenTorusError

data_app = typer.Typer(cls=SortedGroup, help="Acquire datasets with hash + license provenance.")
app.add_typer(data_app, name="data")


def _dataset_connector(source: str):  # noqa: ANN202
    from opentorus.research.dataset_sources import (
        HuggingFaceConnector,
        OsfConnector,
        ZenodoConnector,
    )

    connectors = {
        "zenodo": ZenodoConnector,
        "huggingface": HuggingFaceConnector,
        "osf": OsfConnector,
    }
    if source not in connectors:
        raise OpenTorusError(f"Unknown dataset source '{source}'. Valid: {', '.join(connectors)}.")
    return connectors[source]()


@data_app.command("fetch")
def data_fetch(
    source: str = typer.Argument(..., help="Dataset source: zenodo | huggingface | osf."),
    identifier: str = typer.Argument(..., help="Record id / repo id (e.g. 123 or acme/torus)."),
) -> None:
    """Resolve and fetch a dataset into a hash + license-pinned DATASET artifact."""
    from opentorus.research.datasets import acquire_dataset

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    guard = _build_egress_guard(base, config)
    try:
        connector = _dataset_connector(source)
        guard.authorize(connector.host)
        dataset = acquire_dataset(base, connector, identifier, config=config, egress=guard)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    note = dataset.access_note or ""
    console.print(
        f"[green]{dataset.id}[/green] ({dataset.source}, license={dataset.license}): "
        f"{dataset.title or identifier} — {note}"
    )
    if dataset.sha256:
        console.print(f"  sha256: {dataset.sha256}")


@data_app.command("list")
def data_list() -> None:
    """List acquired datasets."""
    from opentorus.research.datasets import list_datasets

    base = _require_workspace_dir()
    datasets = list_datasets(base)
    if not datasets:
        console.print("[dim]No datasets yet.[/dim]")
        return
    table = Table(title="Datasets")
    table.add_column("ID", style="bold")
    table.add_column("Source")
    table.add_column("License")
    table.add_column("Title")
    table.add_column("sha256", style="dim")
    for ds in datasets:
        table.add_row(
            ds.id,
            ds.source,
            ds.license or "?",
            (ds.title or ds.external_id)[:50],
            (ds.sha256 or "")[:12],
        )
    console.print(table)


@data_app.command("link")
def data_link(
    dataset_id: str = typer.Argument(..., help="Dataset id, e.g. DATASET-0001."),
    exp_id: str = typer.Argument(..., help="Experiment id, e.g. EXP-0001."),
) -> None:
    """Record a dataset as an input to an experiment (graph + manifest provenance)."""
    from opentorus.research.datasets import link_dataset_to_experiment

    base = _require_workspace_dir()
    try:
        link_dataset_to_experiment(base, dataset_id, exp_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Linked[/green] {dataset_id} as input to {exp_id}.")
