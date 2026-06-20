"""OpenTorus CLI — paper commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _build_egress_guard,
    _load_workspace_config,
    _require_workspace_dir,
    _run_problem_extraction,
    app,
    console,
)
from opentorus.errors import OpenTorusError

paper_app = typer.Typer(cls=SortedGroup, help="Register and extract papers.")
app.add_typer(paper_app, name="paper")


@paper_app.command("add")
def paper_add(source: str = typer.Argument(..., help="Local PDF path or URL.")) -> None:
    """Register a local PDF (hash-pinned, auto-parsed) or a URL (unpinned)."""
    from opentorus.research.papers import add_paper, is_paper_parsed

    base = _require_workspace_dir()
    try:
        paper = add_paper(base, source)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    pin = "pinned" if paper.pinned else "unpinned"
    msg = f"[green]{paper.id}[/green] ({paper.source_type}, {pin}): {paper.source}"
    if paper.source_type == "local_pdf" and is_paper_parsed(base, paper):
        msg += f"\n[dim]Parsed → note at .opentorus/{paper.note_path}[/dim]"
    elif paper.source_type == "local_pdf":
        msg += "\n[yellow]Registered but not parsed — PDF may be corrupt or unreadable[/yellow]"
    console.print(msg)


@paper_app.command("ingest")
def paper_ingest() -> None:
    """Register every PDF in papers/inbox/ as PAPER-* and parse reading notes."""
    from opentorus.research.papers import ingest_inbox, is_paper_parsed

    ot_dir = _require_workspace_dir()
    root = ot_dir.parent
    try:
        papers = ingest_inbox(ot_dir, root)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not papers:
        inbox = root / "papers" / "inbox"
        console.print(f"[dim]No PDFs in {inbox} — drop files there, then run again.[/dim]")
        return
    for paper in papers:
        parsed = is_paper_parsed(ot_dir, paper)
        state = f" [parsed] note at .opentorus/{paper.note_path}" if parsed else " [UNREAD]"
        console.print(f"[green]{paper.id}[/green] ← {paper.local_path}{state}")


@paper_app.command("list")
def paper_list() -> None:
    """List registered papers."""
    from opentorus.research.papers import is_paper_parsed, list_papers

    base = _require_workspace_dir()
    papers = list_papers(base)
    if not papers:
        console.print("[dim]No papers yet.[/dim]")
        return
    table = Table(title="Papers")
    table.add_column("ID", style="bold")
    table.add_column("Type")
    table.add_column("Read")
    table.add_column("Pinned")
    table.add_column("Fetch")
    table.add_column("Source")
    for paper in papers:
        from opentorus.research.papers import paper_fetch_identifier

        if not paper.full_text_accessible:
            read_state = "metadata"
        elif is_paper_parsed(base, paper):
            read_state = "parsed"
        else:
            read_state = "[yellow]UNREAD[/yellow]"
        table.add_row(
            paper.id,
            paper.source_type,
            read_state,
            "yes" if paper.pinned else "no",
            paper_fetch_identifier(paper) or "—",
            paper.source,
        )
    console.print(table)


@paper_app.command("fetch")
def paper_fetch(
    identifier: str = typer.Argument(..., help="A DOI (10.x/...) or arXiv id (e.g. 2401.01234)."),
) -> None:
    """Fetch full text for a DOI/arXiv id, cache as PAPER-*, and parse a reading note."""
    from opentorus.research.egress import EgressBlocked
    from opentorus.research.papers import acquire_paper, describe_fetched_paper
    from opentorus.research.sources.base import SourceRecord
    from opentorus.research.sources.crossref import API as CROSSREF_API
    from opentorus.research.sources.crossref import CrossrefSource

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    email = config.tools.literature.contact_email
    guard = _build_egress_guard(base, config)

    ident = identifier.strip()
    try:
        if ident.startswith("10."):
            guard.authorize(CROSSREF_API)
            record = CrossrefSource(contact_email=email).lookup_doi(ident)
            if record is None:
                record = SourceRecord(source="manual", title=ident, doi=ident)
        else:
            record = SourceRecord(source="arxiv", title=f"arXiv:{ident}", arxiv_id=ident)
        paper = acquire_paper(base, record, contact_email=email, egress=guard)
    except EgressBlocked as exc:
        console.print(f"[red]Network egress denied: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    text = describe_fetched_paper(base, paper)
    if paper.full_text_accessible and "[parsed]" in text:
        console.print(f"[green]{text}[/green]")
    else:
        console.print(f"[yellow]{text}[/yellow]")


@paper_app.command("read-unread")
def paper_read_unread() -> None:
    """Parse every cached PDF that has not been read yet."""
    from opentorus.research.papers import is_paper_parsed, list_papers, read_paper

    base = _require_workspace_dir()
    unread = [
        p for p in list_papers(base) if p.full_text_accessible and not is_paper_parsed(base, p)
    ]
    if not unread:
        console.print("[dim]All full-text papers are already parsed.[/dim]")
        return
    for paper in unread:
        try:
            read_paper(base, paper.id)
            console.print(f"[green]{paper.id}[/green] parsed.")
        except OpenTorusError as exc:
            console.print(f"[red]{paper.id}[/red]: {exc}")


@paper_app.command("extract")
def paper_extract(paper_id: str = typer.Argument(..., help="Paper id, e.g. PAPER-0001.")) -> None:
    """Extract text from a registered local PDF."""
    from opentorus.research.papers import extract_paper

    base = _require_workspace_dir()
    try:
        paper = extract_paper(base, paper_id)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{paper.id}[/green] extracted to .opentorus/{paper.text_path}")


@paper_app.command("compile")
def paper_compile(
    tex_path: str = typer.Argument(
        ...,
        help="Workspace-relative .tex file, e.g. solution_note.tex",
    ),
) -> None:
    """Compile a workspace LaTeX file to PDF with the full bibliography cycle."""
    from opentorus.research.authoring import compile_workspace_tex

    ot_dir = _require_workspace_dir()
    root = ot_dir.parent
    try:
        result = compile_workspace_tex(root, tex_path)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]PDF[/green] written to {result.pdf_path}")
    if result.used_bibtex:
        console.print("[dim]Bibliography resolved via bibtex.[/dim]")
    console.print(f"[dim]Log: {result.log_path}[/dim]")


@paper_app.command("problems")
def paper_problems(
    ctx: typer.Context,
    paper_id: str = typer.Argument(..., help="Paper id, e.g. PAPER-0001."),
    heuristic_only: bool = typer.Option(False, "--heuristic-only"),
    llm_only: bool = typer.Option(False, "--llm-only"),
    vision: bool = typer.Option(False, "--vision"),
    from_page: int | None = typer.Option(None, "--from-page", min=1),
    to_page: int | None = typer.Option(None, "--to-page", min=1),
) -> None:
    """Extract open problems from a paper into PROBLEM-* dossiers (alias for `problem extract`)."""
    _run_problem_extraction(
        ctx,
        paper_id=paper_id,
        from_markdown=None,
        heuristic_only=heuristic_only,
        llm_only=llm_only,
        vision=vision,
        from_page=from_page,
        to_page=to_page,
    )
