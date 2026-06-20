"""Offline tests for PDF acquisition and the paper cache (Milestone 43).

The resolver chain and downloader are injected, so no network is touched. We
verify: OA is preferred and respected, paywalls store metadata only, the cache
dedupes by DOI/arXiv id, and artifacts record license + provenance.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.papers import (
    Resolution,
    acquire_paper,
    list_papers,
    resolve_full_text,
)
from opentorus.research.sources.base import SourceRecord
from opentorus.workspace import init_workspace


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return tmp_path / ".opentorus"


def test_resolver_prefers_unpaywall_oa() -> None:
    record = SourceRecord(source="crossref", title="A", doi="10.1/x")
    res = resolve_full_text(
        record,
        contact_email="me@uni.edu",
        unpaywall=lambda doi, email: ("https://oa/pdf", "cc-by"),
    )
    assert res.accessible is True
    assert res.resolver == "unpaywall"
    assert res.pdf_url == "https://oa/pdf"
    assert res.license == "cc-by"


def test_resolver_falls_back_to_arxiv() -> None:
    record = SourceRecord(source="arxiv", title="B", arxiv_id="2401.01234")
    res = resolve_full_text(record, contact_email=None)
    assert res.accessible is True
    assert res.resolver == "arxiv"
    assert res.pdf_url.endswith("2401.01234")


def test_resolver_uses_record_oa_pdf() -> None:
    record = SourceRecord(
        source="openalex", title="C", is_open_access=True, pdf_url="https://x/oa.pdf"
    )
    res = resolve_full_text(record, contact_email=None)
    assert res.accessible is True
    assert res.resolver == "openalex_oa"


def test_resolver_paywall_inaccessible() -> None:
    record = SourceRecord(source="springer", title="D", doi="10.2/pay", is_open_access=False)
    res = resolve_full_text(
        record, contact_email="me@uni.edu", unpaywall=lambda doi, email: (None, None)
    )
    assert res.accessible is False
    assert res.pdf_url is None
    assert "not accessible" in (res.note or "")


def test_acquire_downloads_and_pins(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Tori", arxiv_id="2401.00001", abstract="abc")
    calls: list[str] = []

    def downloader(url: str) -> bytes:
        calls.append(url)
        return b"%PDF-1.4 fake"

    paper = acquire_paper(ot, record, downloader=downloader)
    assert paper.full_text_accessible is True
    assert paper.pinned is True
    assert paper.license  # arXiv license recorded
    assert paper.sha256
    assert paper.local_path and (ot / paper.local_path).is_file()
    assert (ot / "papers" / paper.id / "abstract.txt").read_text() == "abc"
    assert len(calls) == 1


def test_acquire_paywalled_stores_metadata_only(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="ieee", title="Locked", doi="10.9/locked", is_open_access=False)

    def downloader(url: str) -> bytes:  # pragma: no cover - must not be called
        raise AssertionError("paywalled item must not be downloaded")

    paper = acquire_paper(
        ot,
        record,
        contact_email="me@uni.edu",
        downloader=downloader,
        unpaywall=lambda doi, email: (None, None),
    )
    assert paper.full_text_accessible is False
    assert paper.local_path is None
    assert paper.doi == "10.9/locked"
    assert "not accessible" in (paper.access_note or "")


def test_cache_dedupes_by_doi(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="crossref", title="Once", doi="10.3/dup")

    def downloader(url: str) -> bytes:
        return b"%PDF"

    first = acquire_paper(
        ot,
        record,
        contact_email="me@uni.edu",
        downloader=downloader,
        unpaywall=lambda d, e: ("https://oa/p", "cc0"),
    )
    again = acquire_paper(
        ot,
        record,
        contact_email="me@uni.edu",
        downloader=downloader,
        unpaywall=lambda d, e: ("https://oa/p", "cc0"),
    )
    assert first.id == again.id
    assert len(list_papers(ot)) == 1


def test_cache_dedupes_by_arxiv_id(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="X", arxiv_id="2401.55555")
    a = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    b = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    assert a.id == b.id
    assert len(list_papers(ot)) == 1


def test_resolution_model_defaults() -> None:
    res = Resolution()
    assert res.accessible is False
    assert res.pdf_url is None
