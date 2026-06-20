"""OpenTorus CLI — lit commands (split from the former monolithic cli.py)."""

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

lit_app = typer.Typer(cls=SortedGroup, help="Search the literature (arXiv, OpenAlex, etc.).")
app.add_typer(lit_app, name="lit")


_LIT_SOURCE_OPTION = typer.Option(
    None, "--source", "-s", help="Limit to named source(s); repeatable."
)


@lit_app.command("search")
def lit_search(
    query: str = typer.Argument(..., help="Search query (topic, title, keywords)."),
    limit: int = typer.Option(5, "--limit", "-k", help="Max results per source."),
    source: list[str] = _LIT_SOURCE_OPTION,
    field: str | None = typer.Option(
        None, "--field", "-f", help="Field hint (cs, math, bio, physics, ...) to pick sources."
    ),
) -> None:
    """Search enabled literature sources and list matching papers."""
    from opentorus.research.sources import search_all, sources_for_field

    ot_dir = _require_workspace_dir()
    config = _load_workspace_config(ot_dir)
    guard = _build_egress_guard(ot_dir, config)
    if field and not source:
        source = [s.name for s in sources_for_field(config, field)]
    records = search_all(config, query, limit=limit, sources=source or None, egress=guard)
    if not records:
        console.print("No results (or no literature sources enabled in config.tools.literature).")
        return
    table = Table(title=f"Literature: {query}")
    table.add_column("Source", style="dim")
    table.add_column("Year")
    table.add_column("Title")
    table.add_column("OA")
    table.add_column("DOI/ID", style="dim")
    for r in records:
        table.add_row(
            r.source,
            str(r.year or "n.d."),
            r.title if len(r.title) <= 70 else r.title[:67] + "...",
            "yes" if r.is_open_access else ("no" if r.is_open_access is False else "?"),
            r.doi or r.arxiv_id or "",
        )
    console.print(table)


@lit_app.command("cite")
def lit_cite(
    citing: str = typer.Argument(..., help="Citing paper id/DOI/arXiv id."),
    cited: str = typer.Argument(..., help="Cited paper id/DOI/arXiv id (must exist locally)."),
) -> None:
    """Add a citation edge between two locally-known papers."""
    from opentorus.research.knowledge import link_citation

    base = _require_workspace_dir()
    try:
        edge = link_citation(base, citing, cited)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if edge is None:
        console.print(
            f"[yellow]Cited work '{cited}' is not in the local corpus; no edge added.[/yellow]"
        )
        return
    console.print(f"[green]{edge.id}[/green]: {edge.source_id} cites {edge.target_id}")


@lit_app.command("link")
def lit_link(
    paper: str = typer.Argument(..., help="Paper id/DOI/arXiv id."),
    claim: str = typer.Argument(..., help="Claim id, e.g. CLAIM-0001."),
    direction: str = typer.Option(
        "supports", "--direction", "-d", help="supports/contradicts/mixed/neutral."
    ),
    strength: str = typer.Option("moderate", "--strength", help="weak/moderate/strong."),
    summary: str = typer.Option("", "--summary", help="Why this paper is evidence."),
) -> None:
    """Link a paper to a claim as evidence (never changes the claim's status)."""
    from opentorus.research.knowledge import link_paper_to_claim

    base = _require_workspace_dir()
    try:
        evidence, edge, advisory = link_paper_to_claim(
            base, paper, claim, direction=direction, strength=strength, summary=summary
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]{evidence.id}[/green]: {edge.source_id} {edge.relation} {edge.target_id}"
    )
    if advisory:
        console.print(f"[yellow]{advisory}[/yellow]")


@lit_app.command("gaps")
def lit_gaps(
    propose: bool = typer.Option(
        False, "--propose", help="Also record testable hypotheses (evidence, not claims)."
    ),
) -> None:
    """Surface claims that are contradicted or weakly supported by the literature."""
    from opentorus.research.knowledge import find_gaps

    base = _require_workspace_dir()
    gaps = find_gaps(base)
    if not gaps:
        console.print("[green]No weakly-supported or contradicted claims found.[/green]")
        return
    table = Table(title="Research gaps (evidence, not verdicts)")
    table.add_column("Claim", style="bold")
    table.add_column("Status")
    table.add_column("Support")
    table.add_column("Contradict")
    table.add_column("Reasons")
    for gap in gaps:
        table.add_row(
            gap.claim_id,
            gap.status,
            str(gap.support_count),
            str(gap.contradiction_count),
            "; ".join(gap.reasons),
        )
    console.print(table)

    if propose:
        from opentorus.research.knowledge import propose_hypotheses

        hypotheses = propose_hypotheses(base)
        console.print(
            f"\n[green]Recorded {len(hypotheses)} hypothesis memory entr(y/ies)[/green] "
            "(evidence-linked, never auto-promoted to claims):"
        )
        for entry in hypotheses:
            console.print(f"  {entry.id}: {entry.text[:100]}...")


@lit_app.command("doi")
def lit_doi(doi: str = typer.Argument(..., help="A DOI to resolve via Crossref.")) -> None:
    """Resolve a DOI to a single normalized record (via Crossref)."""
    from opentorus.research.sources.crossref import CrossrefSource

    ot_dir = _require_workspace_dir()
    config = _load_workspace_config(ot_dir)
    record = CrossrefSource(contact_email=config.tools.literature.contact_email).lookup_doi(doi)
    if record is None:
        console.print(f"[red]No record found for DOI '{doi}'.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{record.title}[/bold]")
    console.print(f"Authors: {', '.join(record.authors) or '(unknown)'}")
    console.print(f"Year: {record.year or 'n.d.'}   Venue: {record.venue or 'n/a'}")
    console.print(f"DOI: {record.doi}   Citations: {record.citation_count}")
