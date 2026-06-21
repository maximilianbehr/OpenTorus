"""OpenTorus CLI — checkpoint commands (split from the former monolithic cli.py)."""

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

checkpoint_app = typer.Typer(
    cls=SortedGroup, help="Record and restore recoverable checkpoints before edits."
)
app.add_typer(checkpoint_app, name="checkpoint")


@checkpoint_app.command("create")
def checkpoint_create(
    label: str = typer.Argument(..., help="A short label for the checkpoint."),
    branch: str | None = typer.Option(
        None, "--branch", help="Optionally create and switch to a new git branch."
    ),
) -> None:
    """Record the current state as a checkpoint (no auto-commit)."""
    from opentorus.research.checkpoints import create_checkpoint

    ot_dir = _require_workspace_dir()
    root = ot_dir.parent
    try:
        checkpoint = create_checkpoint(root, ot_dir, label, create_branch=branch)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{checkpoint.id}[/green] checkpoint recorded ({checkpoint.kind}).")
    if checkpoint.kind == "git":
        console.print(
            f"  branch={checkpoint.git_branch} commit={(checkpoint.git_commit or '')[:8]} "
            f"dirty={checkpoint.git_dirty}"
        )
        if checkpoint.created_branch:
            console.print(f"  created branch [bold]{checkpoint.created_branch}[/bold]")
    else:
        console.print(f"  manifest of {len(checkpoint.manifest)} file(s) recorded.")


@checkpoint_app.command("restore")
def checkpoint_restore(
    checkpoint_id: str = typer.Argument(..., help="Checkpoint id, e.g. CHECKPOINT-0001."),
    force: bool = typer.Option(
        False, "--force", help="Discard uncommitted changes when checking out (git checkpoints)."
    ),
) -> None:
    """Restore a checkpoint: check out the git commit, or diff a manifest checkpoint."""
    from opentorus.research.checkpoints import restore_checkpoint

    ot_dir = _require_workspace_dir()
    root = ot_dir.parent
    try:
        result = restore_checkpoint(root, ot_dir, checkpoint_id, force=force)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    color = "green" if result.applied else "yellow"
    console.print(f"[{color}]{result.message}[/{color}]")
    if result.kind == "manifest":
        for f in result.added[:20]:
            console.print(f"  [green]+ {f}[/green]")
        for f in result.removed[:20]:
            console.print(f"  [red]- {f}[/red]")


@checkpoint_app.command("list")
def checkpoint_list() -> None:
    """List recorded checkpoints."""
    from opentorus.research.checkpoints import list_checkpoints

    ot_dir = _require_workspace_dir()
    checkpoints = list_checkpoints(ot_dir)
    if not checkpoints:
        console.print("[dim]No checkpoints yet.[/dim]")
        return
    table = Table(title="Checkpoints")
    table.add_column("ID", style="bold")
    table.add_column("Kind")
    table.add_column("Label")
    table.add_column("Ref")
    for cp in checkpoints:
        ref = (cp.git_commit or "")[:8] if cp.kind == "git" else f"{len(cp.manifest)} files"
        table.add_row(cp.id, cp.kind, cp.label, ref)
    console.print(table)
