"""OpenTorus CLI — proof commands (split from the former monolithic cli.py)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _load_workspace_config,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.errors import OpenTorusError

proof_app = typer.Typer(cls=SortedGroup, help="Formal verification (opt-in Lean/Coq backends).")
app.add_typer(proof_app, name="proof")


@proof_app.command("submit")
def proof_submit(
    backend: str = typer.Argument(..., help="Backend name: lean4 | coq."),
    source_file: str = typer.Argument(..., help="Path to the formal source file."),
    claim: str | None = typer.Option(None, "--claim", help="Claim id this proof targets."),
) -> None:
    """Submit a formal proof to an enabled backend and record the attempt."""
    from opentorus.research.verifiers import submit_proof

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    path = Path(source_file)
    if not path.is_file():
        console.print(f"[red]No such source file: {source_file}[/red]")
        raise typer.Exit(code=1)
    try:
        attempt = submit_proof(
            base, config, backend, path.read_text(encoding="utf-8"), claim_id=claim
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not attempt.available:
        console.print(f"[yellow]{attempt.backend} unavailable[/yellow] — formal check not run.")
    elif attempt.accepted:
        version = f" ({attempt.backend_version})" if attempt.backend_version else ""
        console.print(f"[green]{attempt.id} accepted[/green] by {attempt.backend}{version}.")
    else:
        console.print(f"[red]{attempt.id} rejected[/red] by {attempt.backend}.")
    console.print(f"Recorded at .opentorus/{attempt.source_path}")


@proof_app.command("list")
def proof_list() -> None:
    """List formal proof attempts."""
    from opentorus.research.verifiers import list_proofs

    base = _require_workspace_dir()
    proofs = list_proofs(base)
    if not proofs:
        console.print("[dim]No proof attempts yet.[/dim]")
        return
    table = Table(title="Proof attempts")
    table.add_column("ID", style="bold")
    table.add_column("Backend")
    table.add_column("Status")
    table.add_column("Claim")
    for proof in proofs:
        if not proof.available:
            status = "[yellow]unavailable[/yellow]"
        elif proof.accepted:
            status = "[green]accepted[/green]"
        else:
            status = "[red]rejected[/red]"
        table.add_row(proof.id, proof.backend, status, proof.claim_id or "—")
    console.print(table)
