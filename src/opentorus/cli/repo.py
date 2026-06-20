"""OpenTorus CLI — repo commands (split from the former monolithic cli.py)."""

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

repo_app = typer.Typer(cls=SortedGroup, help="Treat external code and its tests as evidence.")
app.add_typer(repo_app, name="repo")


@repo_app.command("clone")
def repo_clone(
    url: str = typer.Argument(..., help="Public repository URL."),
    commit: str = typer.Argument(..., help="Pinned commit SHA or tag (required)."),
) -> None:
    """Clone a public repo at a pinned commit into a REPO artifact."""
    from opentorus.research.repos import clone_repo

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    guard = _build_egress_guard(base, config)
    try:
        repo = clone_repo(base, url, commit, config=config, egress=guard)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]{repo.id}[/green] {repo.name} @ {repo.commit[:12]} (license={repo.license or '?'})"
    )


@repo_app.command("test")
def repo_test(
    repo_id: str = typer.Argument(..., help="Repo id, e.g. REPO-0001."),
    claim: str | None = typer.Option(None, "--claim", help="Claim id to attach evidence to."),
    command: str = typer.Option(
        "python -m pytest -q", "--command", "-c", help="Test command to run in the sandbox."
    ),
) -> None:
    """Run a repo's tests in a sandbox and record the observed result as evidence."""
    from opentorus.research.repos import run_repo_tests

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    try:
        repo, result = run_repo_tests(
            base, repo_id, config=config, claim_id=claim, test_command=command
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    outcome = "passed" if result.exit_code == 0 else f"failed (exit {result.exit_code})"
    color = "green" if result.exit_code == 0 else "yellow"
    console.print(f"[{color}]{repo.name} tests {outcome}[/{color}] (observed, not a verification).")


@repo_app.command("list")
def repo_list() -> None:
    """List cloned code-evidence repositories."""
    from opentorus.research.repos import list_repos

    base = _require_workspace_dir()
    repos = list_repos(base)
    if not repos:
        console.print("[dim]No repos yet.[/dim]")
        return
    table = Table(title="Repos")
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("Commit", style="dim")
    table.add_column("License")
    for repo in repos:
        table.add_row(repo.id, repo.name, repo.commit[:12], repo.license or "?")
    console.print(table)
