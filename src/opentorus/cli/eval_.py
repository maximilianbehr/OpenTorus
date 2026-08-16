"""OpenTorus CLI — eval_ commands (split from the former monolithic cli.py)."""

from __future__ import annotations

from pathlib import Path

import typer

from opentorus.cli._base import (
    SortedGroup,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.errors import OpenTorusError

eval_app = typer.Typer(cls=SortedGroup, help="Run reproducible agent evaluations (evidence only).")
app.add_typer(eval_app, name="eval")


@eval_app.command("run")
def eval_run(
    suite: str = typer.Argument("smoke", help="Eval suite to run (e.g. smoke)."),
    seed: int = typer.Option(0, "--seed", help="Seed recorded in the manifest."),
) -> None:
    """Run an eval suite against the mock provider and write a manifest."""
    from opentorus.evals import run_suite

    ot_dir = _require_workspace_dir()
    try:
        run = run_suite(ot_dir, suite, seed=seed)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    for result in run.results:
        mark = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
        console.print(f"  {mark} {result.name}: {result.detail}")
    console.print(
        f"\n{run.passed}/{run.total} passed. Manifest: {run.manifest_path}\n"
        "[dim]Eval results are evidence about this suite, not proof the agent is good.[/dim]"
    )
    if not run.all_passed:
        raise typer.Exit(code=1)


@eval_app.command("digest")
def eval_digest(
    workspace: list[str] | None = typer.Argument(
        None,
        help=(
            "Workspace directories to summarize (each may be a project root or its "
            ".opentorus/). Defaults to the current workspace."
        ),
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Summarize what a finished run actually did (counts and patterns, not a verdict)."""
    import json as _json

    from opentorus.evals.rundigest import digest_workspace, format_digest

    targets: list[Path] = []
    for raw in workspace or []:
        path = Path(raw)
        targets.append(path if path.name == ".opentorus" else path / ".opentorus")
    if not targets:
        targets = [_require_workspace_dir()]

    digests = [digest_workspace(path) for path in targets]
    if as_json:
        console.print_json(_json.dumps([d.model_dump(mode="json") for d in digests]))
        return
    for index, digest in enumerate(digests):
        if index:
            console.print()
        console.print(format_digest(digest))
    console.print(
        "\n[dim]A digest describes a run; it does not judge the mathematics. "
        "Flags are patterns that have marked stuck runs before, not verdicts.[/dim]"
    )


@eval_app.command("record")
def eval_record(
    golden_dir: str = typer.Option(
        "tests/golden", "--dir", help="Directory to write golden transcripts into."
    ),
) -> None:
    """(Re)record golden transcripts of deterministic mock-provider runs."""
    from opentorus.evals.golden import record_goldens

    names = record_goldens(Path(golden_dir))
    console.print(
        f"[green]Recorded {len(names)} golden(s)[/green] into {golden_dir}: " + ", ".join(names)
    )


@eval_app.command("verify")
def eval_verify(
    golden_dir: str = typer.Option(
        "tests/golden", "--dir", help="Directory holding golden transcripts."
    ),
) -> None:
    """Verify current behavior against recorded golden transcripts."""
    from opentorus.evals.golden import verify_goldens

    results = verify_goldens(Path(golden_dir))
    failed = [r for r in results if not r.matched]
    for result in results:
        mark = "[green]OK[/green]" if result.matched else "[red]DIFF[/red]"
        console.print(f"  {mark} {result.name}")
        if not result.matched and result.diff:
            console.print(result.diff)
    if failed:
        console.print(
            f"\n[red]{len(failed)} golden(s) differ.[/red] "
            "Review the diff; if intended, re-record with `opentorus eval record`."
        )
        raise typer.Exit(code=1)
    console.print(f"\n[green]All {len(results)} golden(s) match.[/green]")
