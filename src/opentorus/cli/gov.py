"""OpenTorus CLI — gov commands (split from the former monolithic cli.py)."""

from __future__ import annotations

from pathlib import Path

import typer

from opentorus.cli._base import (
    SortedGroup,
    _load_workspace_config,
    _require_workspace_dir,
    app,
    console,
)

gov_app = typer.Typer(cls=SortedGroup, help="Governance: budgets, DLP, and model routing.")
app.add_typer(gov_app, name="governance")


@gov_app.command("budget")
def governance_budget(
    session: str | None = typer.Option(None, "--session", help="Limit to one session id."),
) -> None:
    """Show budget alerts against configured caps (breaches are flagged)."""
    from opentorus.governance import budget_alerts

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    alerts = budget_alerts(base, config, session_id=session)
    if not alerts:
        console.print("[dim]No budgets configured (config.governance.budgets).[/dim]")
        return
    for alert in alerts:
        color = "red" if alert.breached else "green"
        console.print(f"[{color}]{alert.message}[/{color}]")


@gov_app.command("scan")
def governance_scan(
    path: str = typer.Argument(..., help="File to scan for secrets/PII before sharing."),
) -> None:
    """Run the pre-egress DLP scan over a file and report any findings."""
    from opentorus.governance import dlp_check

    target = Path(path).expanduser()
    if not target.is_file():
        console.print(f"[red]No such file: {path}[/red]")
        raise typer.Exit(code=1)
    result = dlp_check(target.read_text(encoding="utf-8", errors="replace"))
    if result.allowed:
        console.print("[green]No secrets detected.[/green]")
        return
    console.print(f"[red]{result.reason}[/red]")
    for finding in result.findings:
        console.print(f"  - {finding.kind}: {finding.excerpt}")
    raise typer.Exit(code=1)
