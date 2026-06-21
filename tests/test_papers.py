"""Tests for paper ingestion and source pinning (Milestone 8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.papers import (
    add_paper,
    extract_paper,
    get_paper,
    inbox_dir,
    ingest_inbox,
    list_papers,
    processed_inbox_dir,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_add_local_pdf_is_pinned_with_hash(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    base = _ws(tmp_path)
    paper = add_paper(base, str(pdf))
    assert paper.id == "PAPER-0001"
    assert paper.source_type == "local_pdf"
    assert paper.pinned is True
    assert paper.sha256 and len(paper.sha256) == 64
    assert (base / paper.local_path).is_file()
    assert (base / paper.summary_path).is_file()


def test_add_url_is_unpinned(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/paper.pdf")
    assert paper.source_type == "url"
    assert paper.pinned is False
    assert paper.sha256 is None


def test_add_missing_file_errors(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        add_paper(base, "/nonexistent/path/to/file.pdf")


def test_extract_with_injected_extractor(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    base = _ws(tmp_path)
    add_paper(base, str(pdf))
    paper = extract_paper(base, "PAPER-0001", extractor=lambda p: "extracted text")
    assert paper.text_path is not None
    assert (base / paper.text_path).read_text(encoding="utf-8") == "extracted text"
    assert paper.extraction_method == "custom"


def test_extract_url_paper_errors(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    add_paper(base, "https://example.com/x.pdf")
    with pytest.raises(OpenTorusError):
        extract_paper(base, "PAPER-0001", extractor=lambda p: "x")


def test_list_and_get(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    add_paper(base, "https://example.com/a.pdf")
    add_paper(base, "https://example.com/b.pdf")
    assert len(list_papers(base)) == 2
    assert get_paper(base, "PAPER-0002").source == "https://example.com/b.pdf"
    assert get_paper(base, "PAPER-9999") is None


def test_ingest_inbox_registers_and_moves_pdfs(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    base = _ws(root)
    pdf = inbox_dir(root) / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4 inbox")
    papers = ingest_inbox(base, root)
    assert len(papers) == 1
    assert papers[0].id == "PAPER-0001"
    assert not pdf.is_file()
    assert (processed_inbox_dir(root) / "manual.pdf").is_file()
    assert len(list_papers(base)) == 1


def test_ingest_inbox_empty_returns_no_papers(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    base = _ws(root)
    assert ingest_inbox(base, root) == []


def test_add_paper_parses_arxiv_id_from_url(tmp_path: Path) -> None:
    # `paper add <arxiv URL>` must record the arXiv id (and type) so a later
    # paper_fetch of the same id deduplicates instead of creating a second record.
    base = _ws(tmp_path)
    paper = add_paper(base, "https://arxiv.org/abs/2002.01682")
    assert paper.arxiv_id == "2002.01682"
    assert paper.source_type == "arxiv"


def test_add_paper_strips_version_and_pdf_suffix(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    assert add_paper(base, "https://arxiv.org/abs/2002.01682v3").arxiv_id == "2002.01682"
    # A pdf URL for the same id reuses the existing record (no duplicate).
    before = len(list_papers(base))
    again = add_paper(base, "http://arxiv.org/pdf/2002.01682.pdf")
    assert again.arxiv_id == "2002.01682"
    assert len(list_papers(base)) == before  # deduplicated


def test_add_paper_then_fetch_deduplicates(tmp_path: Path) -> None:
    # The exact run scenario: paper add URL, then the agent fetches the same id.
    from opentorus.research.papers import acquire_paper
    from opentorus.research.sources.base import SourceRecord

    base = _ws(tmp_path)
    added = add_paper(base, "https://arxiv.org/abs/2002.01682")
    fetched = acquire_paper(
        base,
        SourceRecord(source="arxiv", title="arXiv:2002.01682", arxiv_id="2002.01682"),
        downloader=lambda u: b"%PDF fake",
    )
    assert fetched.id == added.id  # same record, not a duplicate PAPER-0002
    assert len(list_papers(base)) == 1
