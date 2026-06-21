"""Paper ingestion with source pinning.

Local PDFs are copied into the workspace and pinned with a SHA-256 hash so that
summaries cannot silently drift when an upstream source changes. URLs are
registered as metadata and marked "unpinned" until downloaded. Local PDFs are
parsed into structure + reading notes automatically (``pypdf`` is a core dependency).
"""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, Field
from pypdf import PdfReader

from opentorus.errors import OpenTorusError
from opentorus.jsonl import next_sequential_id

if TYPE_CHECKING:
    from opentorus.research.egress import EgressGuard
    from opentorus.research.sources.base import SourceRecord

PaperSourceType = Literal["local_pdf", "url", "arxiv", "manual", "doi"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Paper(BaseModel):
    id: str
    source: str
    source_type: PaperSourceType
    title: str | None = None
    retrieved_at: datetime | None = None
    local_path: str | None = None
    sha256: str | None = None
    extraction_method: str | None = None
    text_path: str | None = None
    summary_path: str | None = None
    pinned: bool = False
    # Acquisition provenance (Milestone 43).
    doi: str | None = None
    arxiv_id: str | None = None
    year: int | None = None
    license: str | None = None
    full_text_accessible: bool | None = None
    access_note: str | None = None
    abstract: str | None = None
    source_connector: str | None = None
    citation_count: int | None = None
    # Structured reading (Milestone 45).
    structure_path: str | None = None
    note_path: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


_PAPER_NOTE_TEMPLATE = """\
# {id} — {title}

> **PLACEHOLDER ONLY** — PDF not parsed yet. Re-run `paper fetch` or `paper ingest` \
to parse once full text is cached locally.

## Source

{source}

## Main question

## Contributions

## Methods

## Key assumptions

## Evidence used

## Limitations

## Algorithms or procedures

## Claims relevant to this project

## Open questions

## Possible follow-up tasks
"""


def papers_dir(ot_dir: Path) -> Path:
    return ot_dir / "papers"


def is_paper_parsed(ot_dir: Path, paper: Paper) -> bool:
    """True when ``read_paper`` has produced structure + reading note artifacts."""
    return (papers_dir(ot_dir) / paper.id / "structure.json").is_file()


def paper_fetch_identifier(paper: Paper) -> str | None:
    """Return the ``identifier`` argument for ``paper_fetch``, if known."""
    if paper.doi:
        return paper.doi.strip()
    if paper.arxiv_id:
        return paper.arxiv_id.strip()
    source = (paper.source or "").strip()
    if not source:
        return None
    try:
        from opentorus.research.identifiers import normalize_paper_identifier

        _, ident = normalize_paper_identifier(source)
        return ident
    except Exception:  # noqa: BLE001 — unknown local paths stay without fetch id
        return None


def format_paper_agent_line(paper: Paper, ot_dir: Path | None = None) -> str:
    """One-line summary for paper_list, status, and agent inventory."""
    pin = "pinned" if paper.pinned else "unpinned"
    title = paper.title or "(untitled)"
    chunks = [f"{paper.id} [{paper.source_type}, {pin}] {title}"]
    fetch_id = paper_fetch_identifier(paper)
    if fetch_id:
        chunks.append(f'fetch="{fetch_id}"')
    if ot_dir is not None and paper.full_text_accessible:
        read_tag = "parsed" if is_paper_parsed(ot_dir, paper) else "UNREAD"
        chunks.append(f"[{read_tag}]")
    elif fetch_id and not paper.full_text_accessible:
        if paper.access_note:
            # Already fetched; full text is unavailable and will not change on retry.
            chunks.append("[metadata only — full text unavailable; paper_read, do not re-fetch]")
        else:
            chunks.append("[metadata only — paper_fetch to retrieve full text]")
    elif paper.local_path:
        chunks.append(paper.local_path)
    elif not fetch_id:
        chunks.append("(local only)")
    chunks.append(f'read=paper_read("{paper.id}")')
    return " — ".join(chunks)


def reading_note_excerpt(ot_dir: Path, paper: Paper, *, max_chars: int = 6000) -> str:
    """Return the parsed reading note (or abstract fallback) for agent context."""
    for rel in (paper.note_path, paper.summary_path):
        if not rel:
            continue
        note_file = ot_dir / rel
        if not note_file.is_file():
            continue
        text = note_file.read_text(encoding="utf-8")
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 20].rstrip() + "\n\n… (truncated)"
    if paper.abstract:
        return (
            "Abstract (metadata only — fetch full text with paper_fetch first):"
            f"\n\n{paper.abstract}"
        )
    return "(No reading note yet — use paper_fetch or paper ingest to parse this PAPER-*)"


def _meta_path(paper_dir: Path) -> Path:
    return paper_dir / "metadata.yaml"


def _save_meta(ot_dir: Path, paper: Paper) -> None:
    paper_dir = papers_dir(ot_dir) / paper.id
    paper_dir.mkdir(parents=True, exist_ok=True)
    _meta_path(paper_dir).write_text(
        yaml.safe_dump(paper.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(?P<id>[^\s?#]+)", re.IGNORECASE)


def _normalize_arxiv_id(arxiv_id: str | None) -> str | None:
    """Bare arXiv id without a trailing version (e.g. ``2002.01682v1`` -> ``2002.01682``).

    Applied on both store and compare so a stub added as ``2002.01682`` and a fetch
    record carrying ``2002.01682v1`` resolve to one paper instead of duplicating.
    """
    if not arxiv_id:
        return None
    ident = arxiv_id.strip().removesuffix(".pdf")
    ident = re.sub(r"v\d+$", "", ident)
    return ident or None


def _arxiv_id_from_url(url: str) -> str | None:
    """Extract a version-stripped arXiv id from an arxiv.org URL (abs or pdf).

    ``https://arxiv.org/abs/2002.01682v2`` and ``.../pdf/2002.01682.pdf`` both yield
    ``2002.01682``. Populating this on ``paper add`` lets a later ``paper_fetch`` of
    the same id deduplicate instead of creating a second PAPER-* record.
    """
    match = _ARXIV_URL_RE.search(url)
    if not match:
        return None
    return _normalize_arxiv_id(match.group("id"))


def list_papers(ot_dir: Path) -> list[Paper]:
    base = papers_dir(ot_dir)
    if not base.is_dir():
        return []
    papers: list[Paper] = []
    for child in sorted(base.iterdir()):
        meta = _meta_path(child)
        if child.is_dir() and meta.is_file():
            data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
            papers.append(Paper.model_validate(data))
    return papers


def get_paper(ot_dir: Path, paper_id: str) -> Paper | None:
    for paper in list_papers(ot_dir):
        if paper.id == paper_id:
            return paper
    return None


def _write_summary_placeholder(ot_dir: Path, paper: Paper) -> str:
    summaries = ot_dir / "summaries"
    summaries.mkdir(parents=True, exist_ok=True)
    summary_path = summaries / f"{paper.id}.md"
    summary_path.write_text(
        _PAPER_NOTE_TEMPLATE.format(
            id=paper.id, title=paper.title or "(untitled)", source=paper.source
        ),
        encoding="utf-8",
    )
    return str(summary_path.relative_to(ot_dir))


def inbox_dir(root: Path) -> Path:
    """Workspace-visible drop folder for PDFs the user adds manually."""
    return root / "papers" / "inbox"


def processed_inbox_dir(root: Path) -> Path:
    return inbox_dir(root) / "processed"


def ingest_inbox(ot_dir: Path, root: Path) -> list[Paper]:
    """Register every ``*.pdf`` in ``papers/inbox/`` and move it to ``processed/``."""
    inbox = inbox_dir(root)
    inbox.mkdir(parents=True, exist_ok=True)
    done = processed_inbox_dir(root)
    done.mkdir(parents=True, exist_ok=True)

    ingested: list[Paper] = []
    for pdf in sorted(inbox.glob("*.pdf")):
        paper = add_paper(ot_dir, str(pdf))
        ingested.append(paper)
        target = done / pdf.name
        if target.exists():
            target.unlink()
        shutil.move(str(pdf), str(target))
    return ingested


def add_paper(ot_dir: Path, source: str) -> Paper:
    """Register a local PDF (copied + hash-pinned) or a URL (unpinned).

    An arXiv URL is recognized and its id recorded so a later ``paper_fetch`` of
    the same id reuses this record instead of creating a duplicate; if the id is
    already registered, the existing paper is returned unchanged.
    """
    existing = list_papers(ot_dir)
    arxiv_id = _arxiv_id_from_url(source) if _is_url(source) else None
    if arxiv_id:
        for paper in existing:
            if (paper.arxiv_id or "").strip() == arxiv_id:
                return paper

    paper_id = next_sequential_id("PAPER", len(existing))
    paper_dir = papers_dir(ot_dir) / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    if _is_url(source):
        paper = Paper(
            id=paper_id,
            source=source,
            source_type="arxiv" if arxiv_id else "url",
            arxiv_id=arxiv_id,
            pinned=False,
        )
    else:
        src_path = Path(source).expanduser()
        if not src_path.is_file():
            raise OpenTorusError(
                f"Could not register paper: '{source}' is neither a URL nor an existing file."
            )
        dest = paper_dir / src_path.name
        shutil.copy2(src_path, dest)
        paper = Paper(
            id=paper_id,
            source=source,
            source_type="local_pdf",
            title=src_path.stem,
            retrieved_at=_utcnow(),
            local_path=str(dest.relative_to(ot_dir)),
            sha256=_sha256(dest),
            pinned=True,
            full_text_accessible=True,
        )

    paper.summary_path = _write_summary_placeholder(ot_dir, paper)
    _save_meta(ot_dir, paper)
    return _parse_full_text_if_needed(ot_dir, paper)


def _parse_full_text_if_needed(ot_dir: Path, paper: Paper) -> Paper:
    """Parse a cached PDF into structure + reading note when possible (best-effort)."""
    if not paper.full_text_accessible or not paper.local_path:
        return paper
    if is_paper_parsed(ot_dir, paper):
        return paper
    try:
        return read_paper(ot_dir, paper.id)
    except OpenTorusError:
        return paper
    except Exception:
        # Corrupt or non-PDF bytes — keep the artifact as [UNREAD].
        return paper


def describe_fetched_paper(ot_dir: Path, paper: Paper) -> str:
    """Human-readable summary after fetch (+ auto-parse when full text exists)."""
    line = f"{paper.id}"
    if paper.full_text_accessible:
        parsed = is_paper_parsed(ot_dir, paper)
        state = "parsed" if parsed else "UNREAD (parse failed)"
        line += (
            f": full text cached ({paper.license or 'license unknown'}) — "
            f"{paper.local_path} [{state}]"
        )
        if parsed and paper.note_path:
            line += f"\nnote: .opentorus/{paper.note_path}"
        note = reading_note_excerpt(ot_dir, paper)
        if parsed and note:
            line += f"\n\n--- Reading note ---\n{note}"
    else:
        note = paper.access_note or "full text not accessible"
        line += f": metadata only — {note}"
    return line


ARXIV_LICENSE = "arXiv.org perpetual, non-exclusive license"


class Resolution(BaseModel):
    """The outcome of the full-text resolver chain for one record."""

    pdf_url: str | None = None
    license: str | None = None
    resolver: str | None = None
    accessible: bool = False
    note: str | None = None


def _arxiv_pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def resolve_full_text(
    record: SourceRecord,
    *,
    contact_email: str | None = None,
    unpaywall: Callable[[str, str], tuple[str | None, str | None]] | None = None,
) -> Resolution:
    """Find a *legal* full-text PDF, preferring open access.

    Order (paywalls are never bypassed): Unpaywall (legal OA for a DOI) → arXiv
    preprint → the record's own declared OA PDF → institutional access (Milestone
    44, not yet wired). If nothing legal is found, full text is reported as
    inaccessible and only metadata is stored.
    """
    oa_lookup = unpaywall
    if oa_lookup is None:
        from opentorus.research.sources.unpaywall import best_oa_pdf

        oa_lookup = best_oa_pdf

    if record.doi and contact_email:
        try:
            pdf_url, license_name = oa_lookup(record.doi, contact_email)
        except Exception:  # noqa: BLE001 - a failed resolver must not abort acquisition
            pdf_url, license_name = None, None
        if pdf_url:
            return Resolution(
                pdf_url=pdf_url, license=license_name, resolver="unpaywall", accessible=True
            )

    if record.arxiv_id:
        return Resolution(
            pdf_url=_arxiv_pdf_url(record.arxiv_id),
            license=ARXIV_LICENSE,
            resolver="arxiv",
            accessible=True,
        )

    if record.is_open_access and record.pdf_url:
        return Resolution(
            pdf_url=record.pdf_url,
            resolver=f"{record.source}_oa",
            accessible=True,
        )

    return Resolution(
        accessible=False,
        note="full text not accessible (no legal open-access copy found; "
        "institutional access not configured)",
    )


def _find_cached(ot_dir: Path, record: SourceRecord) -> Paper | None:
    doi = (record.doi or "").lower()
    arxiv_id = (_normalize_arxiv_id(record.arxiv_id) or "").lower()
    for paper in list_papers(ot_dir):
        if doi and (paper.doi or "").lower() == doi:
            return paper
        if arxiv_id and (_normalize_arxiv_id(paper.arxiv_id) or "").lower() == arxiv_id:
            return paper
    return None


def acquire_paper(
    ot_dir: Path,
    record: SourceRecord,
    *,
    contact_email: str | None = None,
    resolver: Callable[..., Resolution] = resolve_full_text,
    downloader: Callable[[str], bytes] | None = None,
    unpaywall: Callable[[str, str], tuple[str | None, str | None]] | None = None,
    egress: EgressGuard | None = None,
) -> Paper:
    """Acquire a paper from a search record: resolve legal full text, cache it.

    Returns the existing artifact if the DOI/arXiv id is already cached (no
    duplicate download). When no legal full text is found, the artifact is stored
    with metadata + abstract only and an honest ``full_text_accessible=False``.
    """
    cached = _find_cached(ot_dir, record)
    # A cached record that already has full text (or a local copy) is reused as-is.
    if cached is not None and (cached.full_text_accessible or cached.local_path):
        return _parse_full_text_if_needed(ot_dir, cached)

    download = downloader
    if download is None:
        from opentorus.research.sources.base import http_get_bytes

        download = http_get_bytes

    resolution = resolver(record, contact_email=contact_email, unpaywall=unpaywall)

    if cached is not None:
        # A metadata-only stub (e.g. from `paper add <arxiv URL>`): resolve and
        # download full text now, upgrading the existing record in place rather than
        # creating a duplicate. Fill in any metadata the stub was missing.
        paper = cached
        paper_dir = papers_dir(ot_dir) / paper.id
        paper_dir.mkdir(parents=True, exist_ok=True)
        paper.title = paper.title or record.title
        paper.doi = paper.doi or record.doi
        paper.arxiv_id = _normalize_arxiv_id(paper.arxiv_id or record.arxiv_id)
        paper.year = paper.year or record.year
        paper.abstract = paper.abstract or record.abstract
        paper.source_connector = paper.source_connector or record.source
        paper.citation_count = paper.citation_count or record.citation_count
        paper.retrieved_at = _utcnow()
        if resolution.license:
            paper.license = resolution.license
    else:
        paper_id = next_sequential_id("PAPER", len(list_papers(ot_dir)))
        paper_dir = papers_dir(ot_dir) / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)

        source_type: PaperSourceType = (
            "doi" if record.doi else ("arxiv" if record.arxiv_id else "url")
        )
        paper = Paper(
            id=paper_id,
            source=record.url or record.doi or record.arxiv_id or record.title,
            source_type=source_type,
            title=record.title,
            retrieved_at=_utcnow(),
            doi=record.doi,
            arxiv_id=_normalize_arxiv_id(record.arxiv_id),
            year=record.year,
            abstract=record.abstract,
            source_connector=record.source,
            citation_count=record.citation_count,
            license=resolution.license,
        )

    if resolution.accessible and resolution.pdf_url:
        if egress is not None:
            egress.authorize(resolution.pdf_url)
        data = download(resolution.pdf_url)
        dest = paper_dir / "paper.pdf"
        dest.write_bytes(data)
        paper.local_path = str(dest.relative_to(ot_dir))
        paper.sha256 = _sha256(dest)
        paper.full_text_accessible = True
        paper.pinned = True
        paper.access_note = f"full text retrieved via {resolution.resolver}"
    else:
        paper.full_text_accessible = False
        paper.access_note = resolution.note or "full text not accessible"

    if record.abstract:
        abstract_path = paper_dir / "abstract.txt"
        abstract_path.write_text(record.abstract, encoding="utf-8")

    paper.summary_path = _write_summary_placeholder(ot_dir, paper)
    _save_meta(ot_dir, paper)
    return _parse_full_text_if_needed(ot_dir, paper)


def _extract_pdf_pages(path: Path) -> list[str]:
    """Extract per-page text from a PDF with ``pypdf``."""
    reader = PdfReader(str(path))
    return [(page.extract_text() or "") for page in reader.pages]


def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF with ``pypdf``."""
    return "\n".join(_extract_pdf_pages(path))


def read_paper(
    ot_dir: Path,
    paper_id: str,
    *,
    page_extractor: Callable[[Path], list[str]] | None = None,
) -> Paper:
    """Parse a local PDF into structure + a fixed-schema reading note.

    Produces ``structure.json`` (abstract, sections with page provenance, and the
    reference list) and a Markdown note under ``summaries/`` that separates what
    the authors state from what is demonstrated. Requires a locally pinned PDF.
    """
    from opentorus.research.reading import (
        build_paper_note,
        parse_structure,
        render_note_markdown,
    )

    paper = get_paper(ot_dir, paper_id)
    if paper is None:
        raise OpenTorusError(f"No paper with id '{paper_id}'.")
    if not paper.local_path:
        raise OpenTorusError(
            f"Paper '{paper_id}' has no local full text to read "
            f"(full_text_accessible={paper.full_text_accessible})."
        )

    pdf_path = ot_dir / paper.local_path
    pages = (page_extractor or _extract_pdf_pages)(pdf_path)
    structure = parse_structure(pages)
    note = build_paper_note(paper_id, structure, title=paper.title)

    paper_dir = papers_dir(ot_dir) / paper_id
    structure_file = paper_dir / "structure.json"
    trimmed = structure.model_copy(deep=True)
    for section in trimmed.sections:
        section.text = section.text[:280]
    structure_file.write_text(trimmed.model_dump_json(indent=2), encoding="utf-8")

    summaries = ot_dir / "summaries"
    summaries.mkdir(parents=True, exist_ok=True)
    note_file = summaries / f"{paper_id}.md"
    note_file.write_text(render_note_markdown(note), encoding="utf-8")
    (paper_dir / "note.json").write_text(note.model_dump_json(indent=2), encoding="utf-8")

    paper.structure_path = str(structure_file.relative_to(ot_dir))
    paper.note_path = str(note_file.relative_to(ot_dir))
    paper.summary_path = paper.note_path
    paper.updated_at = _utcnow()
    _save_meta(ot_dir, paper)
    return paper


def extract_paper(
    ot_dir: Path,
    paper_id: str,
    extractor: Callable[[Path], str] | None = None,
) -> Paper:
    """Extract text from a registered local PDF into ``text.txt``."""
    paper = get_paper(ot_dir, paper_id)
    if paper is None:
        raise OpenTorusError(f"No paper with id '{paper_id}'.")
    if paper.source_type != "local_pdf" or not paper.local_path:
        raise OpenTorusError(
            f"Paper '{paper_id}' has no local file to extract (source_type={paper.source_type})."
        )

    pdf_path = ot_dir / paper.local_path
    text = (extractor or _extract_pdf_text)(pdf_path)

    text_path = papers_dir(ot_dir) / paper_id / "text.txt"
    text_path.write_text(text, encoding="utf-8")

    paper.text_path = str(text_path.relative_to(ot_dir))
    paper.extraction_method = "pypdf" if extractor is None else "custom"
    paper.updated_at = _utcnow()
    _save_meta(ot_dir, paper)
    return paper
