"""OpenTorus CLI -- the approval queue for runs without a terminal."""

from __future__ import annotations

import typer
from rich.markup import escape

from opentorus.cli._base import SortedGroup, _require_workspace_dir, app, console

approvals_app = typer.Typer(
    cls=SortedGroup,
    help="Decide approval requests queued by background runs (no terminal).",
)
app.add_typer(approvals_app, name="approvals")


@approvals_app.command("list")
def approvals_list(
    all_states: bool = typer.Option(
        False, "--all", help="Include approved, denied and used requests."
    ),
) -> None:
    """List pending approval requests (with --all: every request)."""
    from opentorus.approvals import ApprovalQueue

    queue = ApprovalQueue(_require_workspace_dir())
    records = queue.list(None if all_states else "pending")
    if not records:
        console.print("[dim]No approval requests.[/dim]")
        return
    for rec in records:
        console.print(
            f"[bold]{rec['id']}[/bold]  {rec.get('state')}  {escape(str(rec.get('tool')))}"
            f"  [dim]{rec.get('created_at', '')}  policy {rec.get('policy_version')}[/dim]"
        )
        console.print(f"  {escape(str(rec.get('description', '')))}")
        console.print(f"  [dim]{escape(str(rec.get('reason', '')))}[/dim]")


def _decide(approval_id: str, approve: bool) -> None:
    from opentorus.approvals import ApprovalQueue

    queue = ApprovalQueue(_require_workspace_dir())
    try:
        rec = queue.decide(approval_id, approve)
    except ValueError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    verb = "Approved" if approve else "Denied"
    console.print(f"{verb} {rec['id']} ({escape(str(rec.get('tool')))}).")
    if approve:
        console.print(
            "[dim]Single use: it applies to one call with exactly these arguments, "
            "under this policy version.[/dim]"
        )


@approvals_app.command("approve")
def approvals_approve(approval_id: str = typer.Argument(..., help="APPROVAL-… id.")) -> None:
    """Approve one queued request (single use, exact arguments only)."""
    _decide(approval_id, True)


@approvals_app.command("deny")
def approvals_deny(approval_id: str = typer.Argument(..., help="APPROVAL-… id.")) -> None:
    """Deny one queued request."""
    _decide(approval_id, False)
