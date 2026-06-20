"""OpenTorus CLI — patch commands (split from the former monolithic cli.py)."""

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

patch_app = typer.Typer(cls=SortedGroup, help="Manage patches as first-class artifacts.")
app.add_typer(patch_app, name="patch")


@patch_app.command("list")
def patch_list() -> None:
    """List patch artifacts."""
    from opentorus.research.patches import list_patches

    base = _require_workspace_dir()
    patches = list_patches(base)
    if not patches:
        console.print("[dim]No patches yet.[/dim]")
        return
    table = Table(title="Patches")
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Files")
    table.add_column("Reason")
    for patch in patches:
        table.add_row(patch.id, patch.status, str(len(patch.files_changed)), patch.reason)
    console.print(table)


@patch_app.command("show")
def patch_show(patch_id: str = typer.Argument(..., help="Patch id, e.g. PATCH-0001.")) -> None:
    """Show a patch's metadata and diff."""
    from opentorus.research.patches import get_patch, read_diff

    base = _require_workspace_dir()
    patch = get_patch(base, patch_id)
    if patch is None:
        console.print(f"[red]No patch with id '{patch_id}'.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{patch.id}[/bold] [{patch.status}]")
    console.print(f"Reason: {patch.reason}")
    console.print(f"Files: {', '.join(patch.files_changed)}")
    diff = read_diff(base, patch)
    lines = diff.splitlines()
    if len(lines) > 200:
        console.print(f"[dim](diff has {len(lines)} lines; showing first 200)[/dim]")
        diff = "\n".join(lines[:200])
    console.print(diff or "[dim](empty diff)[/dim]")


@patch_app.command("apply")
def patch_apply(patch_id: str = typer.Argument(..., help="Patch id to apply.")) -> None:
    """Apply a proposed patch to the working tree."""
    from opentorus.research.patches import apply_patch_artifact

    base = _require_workspace_dir()
    try:
        patch = apply_patch_artifact(base.parent, base, patch_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{patch.id}[/green] applied. Consider running `opentorus check`.")


@patch_app.command("reject")
def patch_reject(patch_id: str = typer.Argument(..., help="Patch id to reject.")) -> None:
    """Reject a proposed patch without changing files."""
    from opentorus.research.patches import reject_patch

    base = _require_workspace_dir()
    try:
        patch = reject_patch(base, patch_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[yellow]{patch.id}[/yellow] rejected.")


@patch_app.command("revert")
def patch_revert(patch_id: str = typer.Argument(..., help="Patch id to revert.")) -> None:
    """Revert an applied patch, restoring the recorded original contents."""
    from opentorus.research.patches import revert_patch

    base = _require_workspace_dir()
    try:
        patch = revert_patch(base.parent, base, patch_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{patch.id}[/green] reverted.")
