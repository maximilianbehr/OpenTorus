"""OpenTorus CLI — theorem-level literature (THMREF) commands.

``theorem extract`` creates *candidate* references from a locally parsed paper;
``theorem review`` is the only way to accept one; ``theorem check`` records a
deterministic applicability check (exit 2 when rejected); ``theorem coverage``
shows or overrides the category coverage map of a problem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer
from rich.markup import escape
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _load_workspace_config,
    _require_workspace_dir,
    _resolve_problem_id,
    app,
    console,
)
from opentorus.errors import OpenTorusError

if TYPE_CHECKING:
    from opentorus.research.theorems.models import Direction

theorem_app = typer.Typer(
    cls=SortedGroup,
    help=(
        "Theorem-level literature: located theorem references (THMREF), relations, "
        "applicability checks and category coverage. Extraction yields candidates; only "
        "`theorem review --status accepted` accepts a reference."
    ),
)
app.add_typer(theorem_app, name="theorem")


def _fail(exc: Exception) -> None:
    console.print(f"[red]{exc}[/red]")
    raise typer.Exit(code=1) from exc


@theorem_app.command("extract")
def theorem_extract(
    paper_id: str = typer.Argument(..., help="Paper id, e.g. PAPER-0001 (must be parsed)."),
    problem: str | None = typer.Option(
        None, "--problem", help="Attribute the candidates to this PROBLEM-XXXX."
    ),
    llm: bool = typer.Option(
        False,
        "--llm",
        help="Ask the configured model to structure the statements (still candidates).",
    ),
) -> None:
    """Extract candidate theorem references from a parsed local paper."""
    from opentorus.research.theorems.extraction import extract_heuristic, extract_with_llm

    base = _require_workspace_dir()
    pid: str | None = None
    try:
        if problem:
            pid = _resolve_problem_id(base, problem)
        if llm:
            config = _load_workspace_config(base)
            created = extract_with_llm(base, paper_id, problem_id=pid, config=config)
        else:
            created = extract_heuristic(base, paper_id, problem_id=pid)
    except OpenTorusError as exc:
        _fail(exc)
        return
    if not created:
        console.print(
            f"[yellow]No new candidate references for {paper_id.upper()}[/yellow] "
            "(no numbered results found, or all already extracted)."
        )
        return
    for ref in created:
        console.print(
            f"[green]{ref.id}[/green] {escape(ref.theorem_label or '')} (candidate) "
            f"{escape(ref.title)}".rstrip()
        )
    console.print(
        f"[dim]{len(created)} candidate(s). Review with "
        "`opentorus theorem review THMREF-XXXX --status accepted|rejected`.[/dim]"
    )


@theorem_app.command("list")
def theorem_list(
    problem: str | None = typer.Option(None, "--problem", help="Filter by PROBLEM-XXXX."),
    paper: str | None = typer.Option(None, "--paper", help="Filter by PAPER-XXXX."),
    status: str | None = typer.Option(
        None, "--status", help="Filter by review status: candidate|accepted|rejected."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """List theorem references (optionally filtered)."""
    import json as _json

    from opentorus.research.theorems import store

    base = _require_workspace_dir()
    pid = None
    try:
        if problem:
            pid = _resolve_problem_id(base, problem)
        refs = store.list_references(base, problem_id=pid, paper_id=paper, review_status=status)
    except OpenTorusError as exc:
        _fail(exc)
        return
    if as_json:
        console.print_json(_json.dumps([r.model_dump(mode="json") for r in refs]))
        return
    if not refs:
        console.print(
            "[dim]No theorem references. Try `opentorus theorem extract PAPER-0001`.[/dim]"
        )
        return
    table = Table(title="Theorem references")
    table.add_column("id")
    table.add_column("paper")
    table.add_column("label")
    table.add_column("status")
    table.add_column("problem")
    table.add_column("title")
    for ref in refs:
        table.add_row(
            ref.id,
            ref.paper_id,
            ref.theorem_label or "-",
            ref.review_status,
            ref.problem_id or "-",
            ref.title or "",
        )
    console.print(table)


@theorem_app.command("show")
def theorem_show(
    ref_id: str = typer.Argument(..., help="Reference id, e.g. THMREF-0001."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show one theorem reference with its relations and applicability checks."""
    from opentorus.research.theorems import store

    base = _require_workspace_dir()
    try:
        ref = store.require_reference(base, ref_id)
    except OpenTorusError as exc:
        _fail(exc)
        return
    if as_json:
        console.print_json(ref.model_dump_json())
        return
    # Source text can contain brackets ("[GAP]", "[1]"); escape so Rich does not
    # read them as markup.
    console.print(f"[bold]{ref.id}[/bold] {escape(ref.theorem_label or '')} ({ref.review_status})")
    console.print(f"  paper: {ref.paper_id}  problem: {ref.problem_id or '-'}")
    loc = ref.locator
    console.print(
        f"  locator: label={escape(loc.label or '-')} "
        f"page={loc.page if loc.page is not None else '-'} section={escape(loc.section or '-')}"
    )
    if ref.title:
        console.print(f"  title: {escape(ref.title)}")
    console.print(
        f"  extraction: {ref.extraction_method}"
        + (f" ({escape(ref.extracting_model)})" if ref.extracting_model else "")
    )
    if ref.categories:
        console.print("  categories: " + ", ".join(c.value for c in ref.categories))
    if ref.assumptions:
        console.print("  assumptions:")
        for a in ref.assumptions:
            console.print(f"    - {escape(a)}")
    if ref.quantifiers:
        console.print("  quantifiers: " + escape("; ".join(ref.quantifiers)))
    if ref.conclusion:
        console.print(f"  conclusion: {escape(ref.conclusion)}")
    if ref.excerpt:
        console.print(f"  excerpt: {escape(ref.excerpt)}")
    if ref.location_hash:
        console.print(f"  location_hash: {ref.location_hash[:16]}...")
    if ref.review_note:
        console.print(f"  review note: {escape(ref.review_note)}")
    rels = store.list_relations(base, ref_id=ref.id)
    if rels:
        console.print("  relations:")
        for rel in rels:
            console.print(
                f"    {rel.id} {rel.source_ref} --{rel.relation.value}--> {rel.target_ref} "
                f"({rel.provenance}, {rel.review_status})"
            )
    checks = store.list_applicability_checks(base, ref_id=ref.id)
    if checks:
        console.print("  applicability checks:")
        for chk in checks:
            console.print(f"    {chk.id} {chk.problem_id} -> {chk.result.value}")


@theorem_app.command("link")
def theorem_link(
    source: str = typer.Argument(..., help="Source reference id (THMREF-XXXX)."),
    target: str = typer.Argument(
        ..., help="Target reference id (THMREF-XXXX; CLAIM-/OBL- ids allowed for applies-to)."
    ),
    relation: str = typer.Option(
        ...,
        "--relation",
        help=(
            "depends-on | implies | equivalent-to | generalizes | specializes | contradicts | "
            "applies-to | requires-definition"
        ),
    ),
    rationale: str = typer.Option("", "--rationale", help="Why this relation holds."),
) -> None:
    """Record a typed relation between two theorem references (manual provenance)."""
    from opentorus.research.theorems.relations import add_relation

    base = _require_workspace_dir()
    try:
        rel = add_relation(base, source, target, relation, provenance="manual", rationale=rationale)
    except OpenTorusError as exc:
        _fail(exc)
        return
    console.print(
        f"[green]{rel.id}[/green] {rel.source_ref} --{rel.relation.value}--> {rel.target_ref}"
    )


@theorem_app.command("check")
def theorem_check(
    ref_id: str = typer.Argument(..., help="Reference id, e.g. THMREF-0001."),
    problem: str | None = typer.Option(
        None, "--problem", help="Dossier id (defaults to the active problem)."
    ),
    claim: str | None = typer.Option(
        None,
        "--claim",
        help="Dossier claim id; its statement and the dossier assumptions form the context.",
    ),
    assume: Annotated[
        list[str] | None,
        typer.Option("--assume", help="Assumption sentence or THMREF id (repeatable)."),
    ] = None,
    claim_text: str | None = typer.Option(
        None, "--claim-text", help="Claim text to check against (instead of --claim)."
    ),
    direction: str = typer.Option("forward", "--direction", help="forward | converse"),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run the deterministic applicability check (exit 2 when the result is rejected)."""
    from opentorus.research.dossier import store as dossier_store
    from opentorus.research.theorems.applicability import check_applicability

    base = _require_workspace_dir()
    # Narrow the free-form option to the typed ``Direction`` once, here, instead of
    # silencing the checker at the call site.
    checked_direction: Direction
    if direction == "forward":
        checked_direction = "forward"
    elif direction == "converse":
        checked_direction = "converse"
    else:
        console.print("[red]--direction must be 'forward' or 'converse'.[/red]")
        raise typer.Exit(code=1)
    context: list[str] = list(assume or [])
    try:
        pid = _resolve_problem_id(base, problem)
        text = claim_text or ""
        target_id: str | None = None
        if claim:
            record = dossier_store.get_claim(base, pid, claim.strip().upper())
            if record is None:
                raise OpenTorusError(f"No claim '{claim}' in {pid}.")
            target_id = record.id
            text = claim_text or record.statement
            context = [a.statement for a in dossier_store.list_assumptions(base, pid)] + context
        if not text.strip():
            raise OpenTorusError("Provide --claim CLAIM-XXXX or --claim-text TEXT.")
        result = check_applicability(
            base,
            ref_id,
            problem_id=pid,
            assumption_context=context,
            claim_text=text,
            direction=checked_direction,
            target_id=target_id,
        )
    except OpenTorusError as exc:
        _fail(exc)
        return
    if as_json:
        console.print_json(result.model_dump_json())
    else:
        color = {
            "accepted": "green",
            "rejected": "red",
            "inconclusive": "yellow",
            "needs-human-review": "yellow",
        }[result.result.value]
        console.print(
            f"[{color}]{result.id}: {result.result.value.upper()}[/{color}] "
            f"({result.theorem_reference_id} for {result.problem_id})"
        )
        for item in result.checks:
            mark = "ok" if item.passed else ("--" if item.passed is None else "FAIL")
            console.print(f"  {mark:4} {item.name}: {escape(item.detail)}")
        if result.mismatches:
            console.print("[yellow]Mismatches:[/yellow]")
            for mm in result.mismatches:
                console.print(f"  - {escape(mm)}")
        console.print("[dim]An accepted check is a recorded artifact, not a claim promotion.[/dim]")
    if result.result.value == "rejected":
        raise typer.Exit(code=2)


@theorem_app.command("review")
def theorem_review(
    ref_id: str = typer.Argument(..., help="Reference id, e.g. THMREF-0001."),
    status: str = typer.Option(..., "--status", help="accepted | rejected (or candidate)."),
    note: str = typer.Option("", "--note", help="Why (recorded on the reference)."),
    category: Annotated[
        list[str] | None,
        typer.Option(
            "--category",
            help="Coverage category this reference covers (repeatable; replaces the list).",
        ),
    ] = None,
    root_relation: str | None = typer.Option(
        None, "--root-relation", help="Relation to the problem: equivalent | sufficient | ..."
    ),
    problem: str | None = typer.Option(
        None, "--problem", help="Attribute the reference to this PROBLEM-XXXX."
    ),
) -> None:
    """Human review: accept or reject a candidate reference (the only path to accepted)."""
    from opentorus.research.theorems import store

    base = _require_workspace_dir()
    try:
        pid = _resolve_problem_id(base, problem) if problem else None
        ref = store.set_review_status(
            base,
            ref_id,
            status,
            note,
            categories=category,
            root_relation=root_relation,
            problem_id=pid,
        )
    except OpenTorusError as exc:
        _fail(exc)
        return
    console.print(
        f"[green]{ref.id}[/green] {escape(ref.theorem_label or '')} -> {ref.review_status}"
    )


@theorem_app.command("coverage")
def theorem_coverage(
    problem: str | None = typer.Argument(None, help="Dossier id (defaults to the active problem)."),
    mode: str | None = typer.Option(
        None, "--mode", help="prove-or-refute | exploration | survey (critical categories)."
    ),
    set_: tuple[str, str] = typer.Option(
        (None, None),
        "--set",
        help="CATEGORY LEVEL: record a human override for one category.",
        metavar="CATEGORY LEVEL",
    ),
    evidence: Annotated[
        list[str] | None,
        typer.Option("--evidence", help="Artifact id backing the override (repeatable)."),
    ] = None,
    note: str = typer.Option("", "--note", help="Note for the override."),
    record: bool = typer.Option(
        False,
        "--record",
        help="Append this assessment to the coverage ledger as a new COV-NNNN record "
        "(implied by --set; a plain read persists nothing).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show (and optionally override) the literature coverage map of a problem.

    Reading is side-effect free: the map is derived on the fly and only written to
    the ledger when something changed (``--set``) or when asked (``--record``), so
    looking twice does not grow the ledger.
    """
    from opentorus.research.theorems import store
    from opentorus.research.theorems.coverage import assess_coverage

    base = _require_workspace_dir()
    try:
        pid = _resolve_problem_id(base, problem)
        category, level = set_
        overridden = category is not None or level is not None
        if overridden:
            if not category or not level:
                raise OpenTorusError("--set needs both CATEGORY and LEVEL.")
            store.set_coverage_override(
                base, pid, category, level, evidence_ids=list(evidence or []), note=note
            )
        assessment = assess_coverage(base, pid, mode=mode, persist=record or overridden)
    except OpenTorusError as exc:
        _fail(exc)
        return
    if as_json:
        console.print_json(assessment.model_dump_json())
        return
    label = assessment.id or "(derived, not recorded; --record to persist)"
    table = Table(title=f"Coverage {label} for {pid}")
    table.add_column("category")
    table.add_column("level")
    table.add_column("critical")
    table.add_column("provenance")
    table.add_column("evidence")
    critical = set(assessment.critical_categories)
    for key, entry in assessment.entries.items():
        table.add_row(
            key,
            entry.level.value,
            "yes" if entry.category in critical else "",
            entry.provenance,
            ", ".join(entry.evidence_ids[:4]) + (" ..." if len(entry.evidence_ids) > 4 else ""),
        )
    console.print(table)
    if assessment.insufficient:
        console.print(
            "[yellow]Insufficient critical categories:[/yellow] "
            + ", ".join(c.value for c in assessment.insufficient)
        )
    else:
        console.print("[green]All critical categories are at least partially covered.[/green]")
