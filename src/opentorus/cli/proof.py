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

proof_app = typer.Typer(
    cls=SortedGroup, help="Formal verification (Lean/Coq/SMT/interval/sympy backends)."
)
app.add_typer(proof_app, name="proof")


@proof_app.command("submit")
def proof_submit(
    backend: str = typer.Argument(..., help="Backend name: lean4 | coq | smt | interval | sympy."),
    source_file: str = typer.Argument(..., help="Path to the formal source file."),
    claim: str | None = typer.Option(None, "--claim", help="Claim id this proof targets."),
    problem: str | None = typer.Option(
        None,
        "--problem",
        help="Dossier this submission is part of (recorded as provenance, e.g. PROBLEM-0001).",
    ),
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
            base,
            config,
            backend,
            path.read_text(encoding="utf-8"),
            claim_id=claim,
            submitted_under=problem,
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not attempt.available:
        console.print(f"[yellow]{attempt.backend} unavailable[/yellow] — formal check not run.")
    elif attempt.accepted:
        version = f" ({attempt.backend_version})" if attempt.backend_version else ""
        console.print(f"[green]{attempt.id} accepted[/green] by {attempt.backend}{version}.")
        if claim:
            from opentorus.research.verifiers.proofs import can_promote

            promotes, why_not = can_promote(attempt)
            if attempt.statement_bound:
                console.print(f"Statement-bound to {attempt.statement_id}.")
            elif not promotes:
                console.print(f"[yellow]Support only:[/yellow] {why_not}.")
    elif attempt.inconclusive:
        # Timeout/crash/parse failure: the checker gave up. Rendering this as
        # "rejected" told the model its mathematics was wrong when nothing of the
        # sort was established.
        console.print(
            f"[yellow]{attempt.id} inconclusive[/yellow] — {attempt.backend} did not "
            "reach a verdict (not a rejection)."
        )
    else:
        reason = f" ({attempt.rejection})" if attempt.rejection else ""
        console.print(f"[red]{attempt.id} rejected[/red] by {attempt.backend}{reason}.")
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
        elif proof.inconclusive:
            # The checker gave up (timeout/crash/unparseable input) — distinct from a
            # genuine rejection, and rendered as such.
            status = "[yellow]inconclusive[/yellow]"
        else:
            status = "[red]rejected[/red]"
        table.add_row(proof.id, proof.backend, status, proof.claim_id or "—")
    console.print(table)


@proof_app.command("bench")
def proof_bench(
    split: str = typer.Option("dev", "--split", help="dev | heldout."),
    allow_heldout: bool = typer.Option(
        False,
        "--allow-heldout",
        help="Required to score the held-out split (run it once, deliberately).",
    ),
    item: list[str] = typer.Option(  # noqa: B008 — typer idiom
        None, "--item", help="Only these item ids (repeatable)."
    ),
) -> None:
    """Run the frozen formal benchmark: the configured model proves, the Lean gate checks."""
    from opentorus.evals.formal_bench import model_prover, run_benchmark
    from opentorus.providers.registry import get_provider
    from opentorus.research.verifiers.backends import Lean4Backend
    from opentorus.research.verifiers.registry import get_verifier

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    if split not in ("dev", "heldout"):
        console.print("[red]--split must be 'dev' or 'heldout'.[/red]")
        raise typer.Exit(code=1)
    verifier = get_verifier(config, "lean4")
    if not isinstance(verifier, Lean4Backend) or not verifier.is_available():
        console.print(
            "[red]Lean is not enabled/installed (tools.verifiers.lean, lean_command); "
            "the benchmark cannot be checked.[/red]"
        )
        raise typer.Exit(code=1)
    try:
        report = run_benchmark(
            model_prover(get_provider(config)),
            verifier,
            split=split,  # type: ignore[arg-type]
            allow_heldout=allow_heldout,
            item_ids=list(item) if item else None,
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(report.summary(), markup=False, highlight=False)


statement_app = typer.Typer(
    cls=SortedGroup,
    help=(
        "Frozen formal statements (FSTMT-*): the exact Lean/Coq theorem a proof of a "
        "claim must prove. Proposed, then accepted by a human; only a proof bound to an "
        "accepted statement promotes a claim to formally_verified."
    ),
)
proof_app.add_typer(statement_app, name="statement")


@statement_app.command("add")
def statement_add(
    source_file: str = typer.Argument(
        ..., help="Frozen file: preamble + one theorem whose proof is `sorry` (Coq: Admitted)."
    ),
    claim: str = typer.Option(..., "--claim", help="Claim id the statement formalizes."),
    backend: str = typer.Option("lean4", "--backend", help="lean4 | coq."),
    problem: str | None = typer.Option(
        None, "--problem", help="Dossier whose claim store --claim belongs to."
    ),
    note: str = typer.Option("", "--note", help="Why this formalization is faithful."),
) -> None:
    """Propose a frozen formal statement for a claim (binds nothing until accepted)."""
    from opentorus.research.verifiers.statements import propose_statement

    base = _require_workspace_dir()
    path = Path(source_file)
    if not path.is_file():
        console.print(f"[red]No such source file: {source_file}[/red]")
        raise typer.Exit(code=1)
    if not _claim_exists(base, claim, problem):
        console.print(f"[red]No claim '{claim}'" + (f" in {problem}" if problem else "") + "[/red]")
        raise typer.Exit(code=1)
    try:
        record = propose_statement(
            base,
            backend,
            path.read_text(encoding="utf-8"),
            claim_id=claim,
            problem_id=problem,
            note=note,
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[bold]{record.id}[/bold] proposed for {record.claim_id} "
        f"(theorem {record.theorem}, sha256 {record.sha256[:12]}…). "
        f"Review it, then: opentorus proof statement accept {record.id}"
    )


@statement_app.command("accept")
def statement_accept(
    statement_id: str = typer.Argument(..., help="FSTMT-* id."),
    yes: bool = typer.Option(False, "--yes", help="Accept without the interactive prompt."),
) -> None:
    """Accept a proposed statement as the faithful formalization of its claim (human)."""
    from opentorus.research.verifiers.statements import (
        accept_statement,
        get_statement,
        statement_source,
    )

    base = _require_workspace_dir()
    record = get_statement(base, statement_id)
    if record is None:
        console.print(f"[red]No frozen statement '{statement_id}'.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{record.id}[/bold] for {record.claim_id} ({record.backend}):")
    console.print(statement_source(base, record), markup=False, highlight=False)

    def _confirm(_rec: object) -> bool:
        return yes or typer.confirm(
            "Is this the faithful formal statement of the claim? Proofs of it will be "
            "able to promote the claim to formally_verified.",
            default=False,
        )

    try:
        accepted = accept_statement(base, record.id, confirm=_confirm)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{accepted.id} accepted[/green] by {accepted.accepted_by}.")


@statement_app.command("retire")
def statement_retire(statement_id: str = typer.Argument(..., help="FSTMT-* id.")) -> None:
    """Retire a statement: it no longer binds new submissions."""
    from opentorus.research.verifiers.statements import retire_statement

    base = _require_workspace_dir()
    try:
        record = retire_statement(base, statement_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"{record.id} retired.")


@statement_app.command("list")
def statement_list() -> None:
    """List frozen formal statements."""
    from opentorus.research.verifiers.statements import list_statements

    base = _require_workspace_dir()
    records = list_statements(base)
    if not records:
        console.print("[dim]No frozen statements yet.[/dim]")
        return
    table = Table(title="Frozen formal statements")
    for col in ("ID", "Claim", "Backend", "Theorem", "Status", "sha256"):
        table.add_column(col)
    for rec in records:
        claim = f"{rec.problem_id}/{rec.claim_id}" if rec.problem_id else rec.claim_id
        table.add_row(rec.id, claim, rec.backend, rec.theorem, rec.status, rec.sha256[:12])
    console.print(table)


def _claim_exists(base: Path, claim_id: str, problem_id: str | None) -> bool:
    if problem_id:
        from opentorus.research.dossier import store

        return store.get_claim(base, problem_id, claim_id) is not None
    from opentorus.research.claims import get_claim

    return get_claim(base, claim_id) is not None
