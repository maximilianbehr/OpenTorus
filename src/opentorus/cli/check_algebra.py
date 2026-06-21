"""``opentorus check-algebra`` — symbolic sanity check for optimization claims.

Accepts an objective ``W(m)`` either inline (``--expr``) or from a JSON spec (a
path or a literal JSON object), optionally with a claimed optimizer and a domain,
and reports whether the claim survives the calculus (derivative, critical points,
monotonicity, boundary candidates). Built to catch a false interior optimum on a
monotone objective.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opentorus.cli._base import app, console


def _load_spec(source: str | None) -> dict:
    """Parse the positional source into a spec dict: a JSON file path or literal JSON."""
    if not source:
        return {}
    candidate = Path(source)
    text = source
    if candidate.exists():
        text = candidate.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"Source is neither a readable file nor valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise typer.BadParameter("JSON spec must be an object with an 'expression' field.")
    return data


@app.command("check-algebra")
def check_algebra(
    source: str = typer.Argument(
        None,
        help=(
            "A JSON spec — a path to a .json file or a literal JSON object — with keys: "
            "expression, variable, claimed_optimizer, domain ([lo, hi]). "
            "Optional when --expr is given."
        ),
    ),
    expr: str = typer.Option(
        None, "--expr", help="Objective W(m) as an expression, e.g. 'a/m + b*m'."
    ),
    variable: str = typer.Option(None, "--var", help="The variable to optimize over (default: m)."),
    optimizer: str = typer.Option(
        None, "--optimizer", help="Claimed optimizer m* to validate against dW/dm = 0."
    ),
    domain: str = typer.Option(
        None, "--domain", help="Domain 'lo,hi' (e.g. '1,1000') to test monotonicity over."
    ),
    extremum: str = typer.Option(
        None, "--extremum", help="Claimed kind of optimum: 'min' or 'max' (checks curvature)."
    ),
    problem: str = typer.Option(
        None, "--problem", help="Link the check to a dossier (PROBLEM-XXXX) and persist it."
    ),
    claim: str = typer.Option(
        None, "--claim", help="Link the check to a claim (CLAIM-XXXX); a rejection flags it."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit the machine-readable result as JSON."),
) -> None:
    """Check an optimization claim symbolically (derivative, optimum, monotonicity)."""
    from opentorus.research.algebra_check import check_optimizer

    spec = _load_spec(source)
    expression = expr or spec.get("expression")
    if not expression:
        console.print(
            "[red]No expression given.[/red] Pass --expr 'a/m + b*m' or a JSON spec with "
            "an 'expression' field."
        )
        raise typer.Exit(code=1)

    var = variable or spec.get("variable") or "m"
    claimed = optimizer or spec.get("claimed_optimizer")
    extremum_kind = extremum or spec.get("extremum")
    if extremum_kind is not None and extremum_kind not in ("min", "max"):
        console.print("[red]--extremum must be 'min' or 'max'.[/red]")
        raise typer.Exit(code=1)

    dom: tuple[str, str] | None = None
    raw_domain = domain or spec.get("domain")
    if raw_domain is not None:
        parts = raw_domain.split(",") if isinstance(raw_domain, str) else list(raw_domain)
        if len(parts) != 2:
            console.print("[red]--domain must be 'lo,hi' (two values).[/red]")
            raise typer.Exit(code=1)
        dom = (str(parts[0]).strip(), str(parts[1]).strip())

    result = check_optimizer(
        str(expression),
        variable=str(var),
        claimed_optimizer=claimed,
        domain=dom,
        extremum=extremum_kind,
    )

    # When linked to a dossier, persist the check so a rejection reaches the status gate.
    if problem:
        from opentorus.cli._base import _require_workspace_dir, _resolve_problem_id
        from opentorus.research.dossier.algebra_link import record_algebra_check

        base = _require_workspace_dir()
        pid = _resolve_problem_id(base, problem).strip().upper()
        rec = record_algebra_check(base, pid, result, claim_id=claim)
        if not as_json:
            console.print(f"[dim]Recorded {rec.id} under {pid}.[/dim]")

    if as_json:
        console.print_json(result.model_dump_json())
        raise typer.Exit(code=0 if result.verdict != "rejected" else 2)

    color = {
        "consistent": "green",
        "rejected": "red",
        "inconclusive": "yellow",
    }[result.verdict]
    console.print(f"[bold]Objective:[/bold] W({result.variable}) = {result.expression}")
    console.print(f"[bold]dW/d{result.variable}:[/bold] {result.derivative}")
    if result.critical_points:
        console.print(f"[bold]Critical points:[/bold] {', '.join(result.critical_points)}")
    else:
        console.print("[bold]Critical points:[/bold] none found")
    console.print(f"[bold]Monotonicity:[/bold] {result.monotonicity}")
    if result.boundary_candidates:
        console.print(f"[bold]Boundary optima:[/bold] {', '.join(result.boundary_candidates)}")
    if result.claimed_optimizer is not None:
        console.print(
            f"[bold]Claimed optimizer:[/bold] {result.variable}* = {result.claimed_optimizer}"
        )
        console.print(
            f"[bold]dW/d{result.variable} at optimizer:[/bold] {result.optimizer_derivative_value}"
        )
        if result.extremum_kind != "unknown":
            console.print(
                f"[bold]Curvature:[/bold] {result.extremum_kind} "
                f"(W''={result.second_derivative_value})"
            )
    for w in result.warnings:
        console.print(f"[yellow]warning:[/yellow] {w}")
    console.print(f"[{color}]Verdict: {result.verdict.upper()}[/{color}] — {result.detail}")

    # Exit non-zero on a rejected claim so scripts/CI can gate on the check.
    if result.verdict == "rejected":
        raise typer.Exit(code=2)
