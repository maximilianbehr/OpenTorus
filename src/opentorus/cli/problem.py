"""OpenTorus CLI — problem commands (split from the former monolithic cli.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _cli_verbosity,
    _load_workspace_config,
    _require_workspace_dir,
    _resolve_problem_id,
    _run_problem_extraction,
    app,
    console,
)
from opentorus.errors import OpenTorusError

problem_app = typer.Typer(
    cls=SortedGroup,
    help="The credible math dossier workflow (new/show/attack/claim/evidence/report).",
)
app.add_typer(problem_app, name="problem")


@problem_app.command("extract")
def problem_extract(
    ctx: typer.Context,
    paper_id: str | None = typer.Argument(
        None,
        help="Paper id, e.g. PAPER-0001 (omit with --from).",
    ),
    from_markdown: Path | None = typer.Option(
        None,
        "--from",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Extract problems from a markdown file via LLM.",
    ),
    heuristic_only: bool = typer.Option(
        False,
        "--heuristic-only",
        help="Paper extraction only: use heading heuristics and skip the LLM.",
    ),
    llm_only: bool = typer.Option(
        False,
        "--llm-only",
        help="Skip the text-block heuristic and drive extraction with the LLM (papers only).",
    ),
    vision: bool = typer.Option(
        False,
        "--vision",
        help="Render PDF pages to PNG and use a vision model (paper extraction only).",
    ),
    from_page: int | None = typer.Option(None, "--from-page", min=1),
    to_page: int | None = typer.Option(None, "--to-page", min=1),
) -> None:
    """Extract open problems into PROBLEM-* dossiers from a paper or markdown file."""
    _run_problem_extraction(
        ctx,
        paper_id=paper_id,
        from_markdown=from_markdown,
        heuristic_only=heuristic_only,
        llm_only=llm_only,
        vision=vision,
        from_page=from_page,
        to_page=to_page,
    )


@problem_app.command("new")
def problem_new(
    ctx: typer.Context,
    statement: str | None = typer.Argument(
        None,
        help="The problem or conjecture statement.",
    ),
    from_markdown: Path | None = typer.Option(
        None,
        "--from-markdown",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Extract problem dossiers from a markdown file via LLM.",
    ),
    structured: bool = typer.Option(
        False,
        "--structured",
        help="With --from-markdown: split top-level headings into dossiers 1:1 (no LLM).",
    ),
    domain: str = typer.Option("", "--domain", help="Mathematical domain, e.g. 'graph theory'."),
    title: str = typer.Option("", "--title", help="Short title (defaults to the statement)."),
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Tag(s) for the dossier (repeatable).")
    ] = None,
) -> None:
    """Create a new problem dossier under .opentorus/problems/PROBLEM-XXXX/."""
    from opentorus.research.dossier import store

    base = _require_workspace_dir()
    if from_markdown and statement:
        console.print("[red]Provide either STATEMENT or --from-markdown, not both.[/red]")
        raise typer.Exit(code=1)
    if from_markdown and structured:
        from opentorus.research.problem_extraction import split_markdown_problems

        sections = split_markdown_problems(from_markdown.read_text(encoding="utf-8"))
        if not sections:
            console.print("[red]No top-level headings found in the markdown file.[/red]")
            raise typer.Exit(code=1)
        for sec_title, sec_statement in sections:
            dossier = store.create_dossier(
                base,
                sec_statement,
                title=sec_title[:80],
                domain=domain,
                tags=list(tag or []),
            )
            console.print(f"[green]{dossier.id}[/green] — {dossier.title}")
        console.print(
            f"[dim]Created {len(sections)} dossier(s) 1:1 from headings. "
            f"Active: {store.get_active_problem(base)}.[/dim]"
        )
        return
    if from_markdown:
        _run_problem_extraction(
            ctx,
            paper_id=None,
            from_markdown=from_markdown,
            heuristic_only=False,
            llm_only=False,
            vision=False,
            from_page=None,
            to_page=None,
        )
        return
    if statement:
        dossier = store.create_dossier(
            base, statement, title=title, domain=domain, tags=list(tag or [])
        )
        console.print(f"[green]{dossier.id}[/green] created at .opentorus/problems/{dossier.id}/")
        console.print(
            f"[dim]Next: opentorus problem attack {dossier.id} --strategy literature_map[/dim]"
        )
        return
    console.print(
        "[red]Missing statement.[/red] Provide STATEMENT, `--from-markdown FILE.md`, "
        "or use `opentorus problem extract`."
    )
    raise typer.Exit(code=1)


@problem_app.command("refresh-statement")
def problem_refresh_statement(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    paper_id: str | None = typer.Option(
        None,
        "--paper",
        help="PAPER-* source (default: first PAPER-* tag on the dossier).",
    ),
    label: str | None = typer.Option(
        None,
        "--label",
        help="Problem label in the source (default: label:* tag on the dossier).",
    ),
) -> None:
    """Rewrite a dossier statement from the full paper or markdown source block."""
    from opentorus.research.problem_extraction import refresh_dossier_statement_from_source

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    try:
        statement = refresh_dossier_statement_from_source(
            base,
            problem_id,
            paper_id=paper_id,
            label=label,
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Updated[/green] {problem_id} statement ({len(statement)} chars).")
    console.print(f"  .opentorus/problems/{problem_id}/statement.md")


@problem_app.command("list")
def problem_list() -> None:
    """List all problem dossiers."""
    from opentorus.research.dossier import store

    base = _require_workspace_dir()
    dossiers = store.list_dossiers(base)
    if not dossiers:
        console.print('[dim]No problem dossiers yet. Try: opentorus problem new "…"[/dim]')
        return
    table = Table(title="Problem dossiers")
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Domain")
    table.add_column("Title")
    active = store.get_active_problem(base)
    for d in dossiers:
        marker = " ←" if d.id == active else ""
        table.add_row(f"{d.id}{marker}", d.status, d.domain or "—", d.title)
    console.print(table)
    if active:
        console.print(f"[dim]active problem: {active} (commands default to it)[/dim]")


@problem_app.command("use")
def problem_use(
    problem_id: str = typer.Argument(..., help="Dossier id to make active, e.g. PROBLEM-0001."),
) -> None:
    """Set the active problem so other commands can omit the id."""
    from opentorus.research.dossier import store

    base = _require_workspace_dir()
    pid = problem_id.strip().upper()
    try:
        store.require_dossier(base, pid)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    store.set_active_problem(base, pid)
    console.print(f"[green]Active problem set to {pid}.[/green] Commands now default to it.")


@problem_app.command("show")
def problem_show(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
) -> None:
    """Print a dossier summary with the full problem statement."""
    from opentorus.research.dossier import store
    from opentorus.research.dossier.experiments import list_experiments

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    try:
        d = store.require_dossier(base, problem_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold]{d.id}[/bold] — {d.title}")
    console.print(f"  status: {d.status} | formalization: {d.formalization_status}")
    if d.domain:
        console.print(f"  domain: {d.domain}")
    if d.tags:
        console.print(f"  tags: {', '.join(d.tags)}")
    config = _load_workspace_config(base)
    statement = store.statement_body_for_display(store.read_statement(base, problem_id))
    console.print("\n  statement:")
    if statement:
        transform = None
        if config.ui.render_math:
            from opentorus.mathtext import render_math_line

            transform = render_math_line
        for line in statement.splitlines():
            text = transform(line) if transform is not None else line
            console.print(f"    {text}" if text.strip() else "")
    else:
        console.print("    [dim](empty)[/dim]")

    counts = {
        "definitions": len(store.list_definitions(base, problem_id)),
        "assumptions": len(store.list_assumptions(base, problem_id)),
        "known results": len(store.list_known_results(base, problem_id)),
        "related papers": len(store.list_related_papers(base, problem_id)),
        "approaches": len(store.list_approaches(base, problem_id)),
        "claims": len(store.list_claims(base, problem_id)),
        "evidence": len(store.list_evidence(base, problem_id)),
        "experiments": len(list_experiments(base, problem_id)),
        "proof attempts": len(store.list_proof_attempts(base, problem_id)),
        "failed attempts": len(store.list_failed_attempts(base, problem_id)),
    }
    console.print("\n  artifacts:")
    for name, n in counts.items():
        console.print(f"    {name}: {n}")

    # The agent's exp_run / claim / evidence tools record to the workspace-global
    # research store, tagged with the active problem id. Surface the counts
    # attributed to this dossier so a productive `prove` run is reflected here.
    from opentorus.research.claims import list_claims as _ws_list_claims
    from opentorus.research.evidence import list_evidence as _ws_list_evidence
    from opentorus.research.experiments import list_experiments as _ws_list_experiments

    single_dossier = len(store.list_dossiers(base)) == 1

    def _attributed(records: list) -> tuple[int, int]:
        """(count attributed to this problem, count unattributed to any problem)."""
        tagged = sum(1 for r in records if getattr(r, "problem_id", None) == problem_id)
        untagged = sum(1 for r in records if getattr(r, "problem_id", None) is None)
        # In a single-dossier workspace, legacy untagged artifacts can only be this one.
        return (tagged + untagged, 0) if single_dossier else (tagged, untagged)

    ws_claims = _attributed(_ws_list_claims(base))
    ws_evidence = _attributed(_ws_list_evidence(base))
    ws_experiments = _attributed(_ws_list_experiments(base))
    if any(here for here, _ in (ws_claims, ws_evidence, ws_experiments)):
        console.print("\n  research store (attributed to this problem):")
        console.print(f"    claims: {ws_claims[0]}")
        console.print(f"    evidence: {ws_evidence[0]}")
        console.print(f"    experiments: {ws_experiments[0]}")
    unattributed = ws_claims[1] + ws_evidence[1] + ws_experiments[1]
    if unattributed:
        console.print(
            f"    [dim](+{unattributed} workspace artifacts not attributed to any problem)[/dim]"
        )

    claims = store.list_claims(base, problem_id)
    if claims:
        table = Table(title="Claims")
        table.add_column("ID", style="bold")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Statement")
        for c in claims:
            stmt = c.statement if len(c.statement) <= 60 else c.statement[:57] + "…"
            table.add_row(c.id, c.type, c.status, stmt)
        console.print(table)


@problem_app.command("attack")
def problem_attack(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    strategy: str = typer.Option(..., "--strategy", help="Attack strategy template."),
) -> None:
    """Create a structured research approach from a strategy template."""
    from opentorus.research.dossier.models import ATTACK_STRATEGIES
    from opentorus.research.dossier.strategies import create_approach

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    if strategy not in ATTACK_STRATEGIES:
        console.print(
            f"[red]Unknown strategy '{strategy}'.[/red] Choose one of: "
            + ", ".join(ATTACK_STRATEGIES)
        )
        raise typer.Exit(code=1)
    try:
        approach = create_approach(base, problem_id, strategy)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{approach.id}[/green] ({approach.strategy}) added to {problem_id}.")
    console.print(f"  objective: {approach.objective}")
    console.print(f"  card: .opentorus/problems/{problem_id}/approaches/{approach.id}.md")


@problem_app.command("claim")
def problem_claim(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    claim_type: str = typer.Option(
        ..., "--type", help="Claim type (e.g. CONJECTURE, OBSERVATION)."
    ),
    statement: str = typer.Option(..., "--statement", help="The claim statement."),
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Source artifact id(s), e.g. PAPER-0001 (repeatable)."),
    ] = None,
) -> None:
    """Add a typed claim to a dossier (CLI form of `claim add`)."""
    from opentorus.research.dossier import claims
    from opentorus.research.dossier.models import CLAIM_TYPES

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    ctype = claim_type.upper()
    if ctype not in CLAIM_TYPES:
        console.print(
            f"[red]Unknown claim type '{claim_type}'.[/red] Valid: " + ", ".join(CLAIM_TYPES)
        )
        raise typer.Exit(code=1)
    try:
        claim = claims.add_claim(
            base,
            problem_id,
            claim_type=ctype,
            statement=statement,
            source_artifacts=list(source or []),
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{claim.id}[/green] ({claim.type}, {claim.status}): {claim.statement}")


@problem_app.command("evidence")
def problem_evidence(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    claim: str = typer.Option(..., "--claim", help="Claim id, e.g. CLAIM-0001."),
    evidence_type: str = typer.Option(
        ..., "--type", help="Evidence type (e.g. EXPERIMENT, PAPER)."
    ),
    summary: str = typer.Option("", "--summary", help="What the evidence shows."),
    direction: str = typer.Option("supports", "--direction", help="supports|contradicts|neutral."),
    path: str | None = typer.Option(None, "--path", help="Path to an evidence artifact."),
) -> None:
    """Link evidence to a claim (evidence supports, never proves)."""
    from opentorus.research.dossier import claims as claim_ops
    from opentorus.research.dossier.models import EVIDENCE_TYPES

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    etype = evidence_type.upper()
    if etype not in EVIDENCE_TYPES:
        console.print(
            f"[red]Unknown evidence type '{evidence_type}'.[/red] Valid: "
            + ", ".join(EVIDENCE_TYPES)
        )
        raise typer.Exit(code=1)
    if direction not in ("supports", "contradicts", "neutral"):
        console.print("[red]direction must be supports|contradicts|neutral.[/red]")
        raise typer.Exit(code=1)
    try:
        evidence, advisory = claim_ops.add_evidence(
            base,
            problem_id,
            claim,
            evidence_type=etype,
            summary=summary,
            direction=direction,  # type: ignore[arg-type]
            path=path,
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{evidence.id}[/green] → {claim} ({evidence.type}, {evidence.direction})")
    if advisory:
        console.print(f"[yellow]Note: {advisory}[/yellow]")


@problem_app.command("attempt")
def problem_attempt(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    method: str = typer.Option(..., "--method", help="The method that was attempted."),
    reason: str = typer.Option(..., "--reason", help="Why it failed."),
    summary: str = typer.Option("", "--summary", help="Short summary of the attempt."),
    obstruction: bool = typer.Option(
        False, "--obstruction", help="Mark the failure as a reusable obstruction."
    ),
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Tag(s) (repeatable).")] = None,
) -> None:
    """Record a failed attempt (CLI form of `attempt fail`)."""
    from opentorus.research.dossier import store

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    try:
        rec = store.add_failed_attempt(
            base,
            problem_id,
            attempted_method=method,
            summary=summary,
            reason_failed=reason,
            reusable_obstruction=obstruction,
            tags=list(tag or []),
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{rec.id}[/green]: {rec.attempted_method} — {rec.reason_failed}")
    if rec.reusable_obstruction:
        console.print(
            "[dim]Marked as a reusable obstruction; do not retry without a new assumption.[/dim]"
        )


@problem_app.command("experiment")
def problem_experiment(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    title: str = typer.Option(..., "--title", help="Experiment title."),
    command: str = typer.Option(..., "--command", help="Shell command to reproduce the run."),
    seed: int | None = typer.Option(None, "--seed", help="Random seed (required if randomized)."),
    claim: Annotated[
        list[str] | None, typer.Option("--claim", help="Claim id(s) this experiment bears on.")
    ] = None,
    run: bool = typer.Option(False, "--run", help="Execute the experiment now and capture logs."),
) -> None:
    """Create a reproducible experiment manifest (optionally run it)."""
    from opentorus.research.dossier.experiments import create_experiment, run_experiment

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    try:
        exp = create_experiment(
            base,
            problem_id,
            title=title,
            command=command,
            random_seed=seed,
            claim_links=list(claim or []),
        )
        if run:
            exp = run_experiment(base, problem_id, exp.experiment_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    loc = f".opentorus/problems/{problem_id}/experiments/{exp.experiment_id}/"
    console.print(f"[green]{exp.experiment_id}[/green] [{exp.status}]: {exp.title}")
    console.print(f"  manifest: {loc}manifest.yaml")
    if run:
        console.print(f"  result: {exp.result_summary}")


@problem_app.command("proof")
def problem_proof(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    title: str = typer.Option(..., "--title", help="Short title for the proof attempt."),
    body: str = typer.Option(..., "--body", help="The sketch text (mark gaps explicitly)."),
    kind: str = typer.Option("sketch", "--kind", help="sketch|formal."),
    gap: Annotated[
        list[str] | None,
        typer.Option("--gap", help="An explicit gap in the argument (repeatable)."),
    ] = None,
    claim: Annotated[
        list[str] | None, typer.Option("--claim", help="Claim id(s) this proof bears on.")
    ] = None,
) -> None:
    """Record a proof sketch (or formal attempt). A sketch is never a verified proof."""
    from opentorus.research.dossier import claims as claim_ops

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    try:
        proof = claim_ops.add_proof_attempt(
            base,
            problem_id,
            title=title,
            body=body,
            kind=kind,
            gaps=list(gap or []),
            claim_links=list(claim or []),
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{proof.id}[/green] [{proof.status}]: {proof.title}")
    console.print(f"  body: .opentorus/problems/{problem_id}/{proof.body_path}")
    console.print(
        "[dim]A sketch is NOT a verified proof; only a verifier sets formally_verified.[/dim]"
    )


@problem_app.command("report")
def problem_report(
    ctx: typer.Context,
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    lint: bool = typer.Option(False, "--lint", help="Only run the honesty linter on report.md."),
    changelog: bool = typer.Option(
        False, "--changelog", help="Only print the epistemic status-change log for the dossier."
    ),
    compose_llm: bool = typer.Option(
        True,
        "--compose-llm/--no-compose-llm",
        help=(
            "Write LLM narrative report as preprint LaTeX (default: on when a model is configured)."
        ),
    ),
) -> None:
    """Build artifact report.md and optionally an LLM-composed preprint LaTeX report."""
    from opentorus.errors import ProviderError
    from opentorus.providers.registry import get_provider
    from opentorus.research.dossier.pdf_export import ReportComposeHooks
    from opentorus.research.dossier.report import build_report, lint_dossier_report
    from opentorus.ux import compose_progress_label, configure_llm_cli_hooks

    verbose, debug = _cli_verbosity(ctx)
    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    pid = problem_id.strip().upper()
    try:
        if changelog:
            from opentorus.research.dossier import store

            store.require_dossier(base, pid)
            changes = store.list_status_changes(base, pid)
            if not changes:
                console.print("[dim]No status changes recorded yet.[/dim]")
                return
            console.print(f"[bold]Status changelog — {pid}[/bold]")
            for ch in changes:
                when = ch.created_at.date().isoformat()
                via = f" via {ch.artifact}" if ch.artifact else ""
                reason = f" — {ch.reason}" if ch.reason else ""
                console.print(
                    f"  {when} · {ch.claim_id}: {ch.from_status} → {ch.to_status}{via}{reason}"
                )
            return
        if lint:
            issues = lint_dossier_report(base, pid)
            if not issues:
                console.print("[green]No honesty warnings.[/green] Report matches its artifacts.")
                return
            console.print(f"[yellow]{len(issues)} honesty warning(s):[/yellow]")
            for i in issues:
                console.print(f"  line {i.line} [{i.kind.value}] '{i.phrase}': {i.suggestion}")
            raise typer.Exit(code=1) from None
        build_report(base, pid)
        if compose_llm:
            provider = None
            try:
                config = _load_workspace_config(base)
                provider = get_provider(config)
            except ProviderError as exc:
                console.print(f"[yellow]LLM unavailable ({exc}); artifact report only.[/yellow]")
            if provider is not None:
                from opentorus.research.dossier import store
                from opentorus.research.dossier.pdf_export import compose_narrative_tex

                llm_hooks = configure_llm_cli_hooks(console, verbose=verbose, debug=debug)
                indicator = llm_hooks.indicator
                stream_llm = llm_hooks.stream_llm and provider.supports_streaming

                def on_progress(msg: str) -> None:
                    if indicator is not None:
                        indicator.update(compose_progress_label(msg))

                hooks = ReportComposeHooks(
                    on_progress=on_progress,
                    on_llm_text=llm_hooks.on_llm_text,
                    on_llm_thinking=llm_hooks.on_thinking,
                    on_llm_request=llm_hooks.on_llm_request,
                    on_llm_response=llm_hooks.on_llm_response,
                    stream_llm=stream_llm,
                )
                narrative_path = store.dossier_dir(base, pid) / f"{pid}-narrative.tex"
                try:
                    if indicator is not None:
                        indicator.update("Gathering artifacts")
                    doc = compose_narrative_tex(
                        base, pid, provider=provider, compose_llm=True, hooks=hooks
                    )
                    narrative_path.write_text(doc, encoding="utf-8")
                finally:
                    if indicator is not None:
                        indicator.stop()
                if llm_hooks.on_llm_request is not None:
                    console.print()
                console.print(f"[green]Narrative report[/green] → {narrative_path}")
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not lint:
        console.print(f"[green]Artifact report[/green] at .opentorus/problems/{pid}/report.md")


@problem_app.command("referee")
def problem_referee(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    apply_downgrades: bool = typer.Option(
        False,
        "--apply-downgrades",
        help="Apply recommended THEOREM→CONJECTURE downgrades to the ledger (logged, reversible).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit the machine-readable report as JSON."),
) -> None:
    """Run the hostile referee over a dossier (classify claims, find overclaims, gate)."""
    from opentorus.research.dossier.referee import referee_review

    base = _require_workspace_dir()
    pid = _resolve_problem_id(base, problem_id).strip().upper()
    try:
        report = referee_review(base, pid, apply_downgrades=apply_downgrades)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if as_json:
        console.print_json(report.model_dump_json())
    else:
        color = {"pass": "green", "revise": "yellow", "block": "red"}[report.verdict]
        console.print(f"[{color}]Referee verdict: {report.verdict.upper()}[/{color}]")
        console.print(f"Derived report status: [bold]{report.report_status}[/bold]")
        console.print(report.summary)
        if report.downgrades_recommended:
            console.print("[yellow]Recommended downgrades:[/yellow]")
            for d in report.downgrades_recommended:
                console.print(f"  {d}")
        if report.contradictions:
            console.print("[red]Contradictions:[/red]")
            for c in report.contradictions:
                console.print(f"  {c}")
        if report.overclaims:
            console.print(f"[yellow]{len(report.overclaims)} overclaim(s):[/yellow]")
            for o in report.overclaims:
                console.print(f"  {o.location} [{o.kind}] '{o.phrase}'")
        console.print(f"[dim]Full report → .opentorus/problems/{pid}/referee/{report.id}.md[/dim]")
    # Exit non-zero on a blocking verdict so scripts/CI can gate on the referee.
    if report.verdict == "block":
        raise typer.Exit(code=2)


@problem_app.command("export")
def problem_export(
    ctx: typer.Context,
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    pdf: bool = typer.Option(
        False,
        "--pdf",
        help="Also render PDF via preprint LaTeX (requires TeX Live / MacTeX on PATH).",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip the model; emit the MathJax HTML report instead of a PDF "
        "(a model is required to render mathematics in the PDF).",
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Output path (.md, .pdf, or directory). Defaults to dossier folder.",
    ),
    no_refresh: bool = typer.Option(
        False,
        "--no-refresh",
        help="Use existing report.md instead of rebuilding from artifacts.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Emit the PDF even if it overclaims or the dossier status is INVALID.",
    ),
) -> None:
    """Export dossier report + proof sketches as merged Markdown (and optional PDF)."""
    from opentorus.errors import ProviderError
    from opentorus.providers.registry import get_provider
    from opentorus.research.dossier.export import export_problem
    from opentorus.research.dossier.pdf_export import ReportComposeHooks
    from opentorus.ux import compose_progress_label, configure_llm_cli_hooks

    verbose, debug = _cli_verbosity(ctx)
    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    pid = problem_id.strip().upper()
    provider = None
    use_llm = pdf and not no_llm
    if use_llm:
        try:
            config = _load_workspace_config(base)
            provider = get_provider(config)
        except ProviderError as exc:
            console.print(f"[yellow]LLM unavailable ({exc}); using template LaTeX.[/yellow]")
            use_llm = False

    llm_hooks = configure_llm_cli_hooks(console, verbose=verbose, debug=debug)
    indicator = llm_hooks.indicator
    stream_llm = False
    if use_llm and provider is not None:
        stream_llm = llm_hooks.stream_llm and provider.supports_streaming

    def on_progress(msg: str) -> None:
        if indicator is not None:
            indicator.update(compose_progress_label(msg))

    hooks = ReportComposeHooks(
        on_progress=on_progress,
        on_llm_text=llm_hooks.on_llm_text if use_llm else None,
        on_llm_thinking=llm_hooks.on_thinking if use_llm else None,
        on_llm_request=llm_hooks.on_llm_request if use_llm else None,
        on_llm_response=llm_hooks.on_llm_response if use_llm else None,
        stream_llm=stream_llm if use_llm else None,
    )

    result = None
    try:
        if indicator is not None:
            indicator.update("Assembling report")
        result = export_problem(
            base,
            pid,
            out=Path(out) if out else None,
            pdf=pdf,
            refresh_report=not no_refresh,
            provider=provider,
            compose_llm=not no_llm,
            hooks=hooks,
            allow_overclaims=force,
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        if indicator is not None:
            indicator.stop()

    if llm_hooks.on_llm_request is not None:
        console.print()

    assert result is not None
    console.print(f"[green]Markdown[/green] → {result.markdown_path}")
    if result.tex_path is not None:
        console.print(f"[green]LaTeX[/green] → {result.tex_path}")
    if result.pdf_path is not None:
        console.print(f"[green]PDF[/green] → {result.pdf_path}")
    if result.html_path is not None:
        console.print(f"[green]HTML[/green] → {result.html_path}")
        console.print(
            "[yellow]No LaTeX engine found on PATH; wrote HTML instead of PDF. "
            "Install TeX Live / MacTeX for PDF output.[/yellow]"
        )
    elif pdf and result.pdf_path is None:
        console.print("[yellow]PDF was not written.[/yellow]")


@problem_app.command("replay")
def problem_replay(
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    run: bool = typer.Option(
        False, "--run", help="Re-execute each experiment instead of printing."
    ),
) -> None:
    """Print (or re-execute) the reproducibility chain of a dossier's experiments."""
    from opentorus.research.dossier import store
    from opentorus.research.dossier.experiments import list_experiments, run_experiment

    base = _require_workspace_dir()
    problem_id = _resolve_problem_id(base, problem_id)
    try:
        store.require_dossier(base, problem_id)
        experiments = list_experiments(base, problem_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not experiments:
        console.print("[dim]No experiments to replay.[/dim]")
        return
    for exp in experiments:
        console.print(f"[bold]{exp.experiment_id}[/bold] — {exp.title}")
        console.print(f"  command: {exp.command}")
        console.print(f"  seed: {exp.random_seed} | python: {exp.python_version}")
        console.print(f"  git: {exp.git_commit or '(unknown)'} | deps: {exp.dependencies_hash}")
        if run:
            result = run_experiment(base, problem_id, exp.experiment_id)
            console.print(f"  → {result.status}: {result.result_summary}")
