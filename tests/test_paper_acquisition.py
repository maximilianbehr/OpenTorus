"""Offline tests for PDF acquisition and the paper cache (Milestone 43).

The resolver chain and downloader are injected, so no network is touched. We
verify: OA is preferred and respected, paywalls store metadata only, the cache
dedupes by DOI/arXiv id, and artifacts record license + provenance.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
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


def test_arxiv_placeholder_title_is_replaced_by_the_real_one(tmp_path: Path) -> None:
    """A stored ``arXiv:<id>`` title must not survive a fetch that knows the real one.

    The upgrade path reads ``paper.title or record.title``, and a placeholder is
    truthy — so every arXiv paper kept its id as its title forever, including the ones
    already on disk. Re-fetching now repairs them.
    """
    ot = _ot(tmp_path)
    stub = SourceRecord(source="arxiv", title="arXiv:2407.19341", arxiv_id="2407.19341")
    first = acquire_paper(ot, stub, downloader=lambda u: b"%PDF")
    assert first.title == "arXiv:2407.19341"

    real = SourceRecord(
        source="arxiv",
        title="Spectral Bounds for Cliques",
        arxiv_id="2407.19341v1",
        year=2024,
    )
    again = acquire_paper(ot, real, downloader=lambda u: b"%PDF")
    assert again.id == first.id, "must upgrade in place, not duplicate the paper"
    assert again.title == "Spectral Bounds for Cliques"
    assert again.year == 2024


def test_a_real_title_is_never_overwritten(tmp_path: Path) -> None:
    """The repair only touches placeholders — a known title stays put."""
    ot = _ot(tmp_path)
    good = SourceRecord(source="arxiv", title="Spectral Bounds", arxiv_id="2407.19341")
    first = acquire_paper(ot, good, downloader=lambda u: b"%PDF")
    later = SourceRecord(source="arxiv", title="(untitled)", arxiv_id="2407.19341")
    again = acquire_paper(ot, later, downloader=lambda u: b"%PDF")
    assert again.id == first.id
    assert again.title == "Spectral Bounds"


def test_paper_fetch_stores_the_looked_up_arxiv_title(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """``paper_fetch`` on an arXiv id stores the real title, year and abstract.

    It used to store ``arXiv:<id>`` as the title with year and abstract left null,
    while a DOI fetched by the same tool got all three from crossref. A title field
    holding a string that reads as a title but is really the id is worse than an
    honest blank: nothing downstream can tell it is missing.
    """
    from opentorus.research.sources import arxiv as arxiv_module
    from opentorus.tools.base import ToolCall
    from opentorus.tools.research import PaperFetchTool

    ot = _ot(tmp_path)
    config = default_config()
    # trusted + autonomous is the only combination that needs no per-host prompt;
    # the point here is the stored metadata, not the consent path.
    config.permissions.mode = "trusted"
    config.agent.style = "autonomous"

    monkeypatch.setattr(
        arxiv_module.ArxivSource,
        "lookup_id",
        lambda self, ident: SourceRecord(
            source="arxiv",
            title="Spectral Bounds for Cliques",
            arxiv_id=ident,
            year=2024,
            abstract="An abstract.",
        ),
    )
    monkeypatch.setattr(
        "opentorus.research.sources.base.http_get_bytes", lambda url, **kw: b"%PDF-1.4 x"
    )

    tool = PaperFetchTool(ot, config)
    result = tool.run(ToolCall(name="paper_fetch", args={"identifier": "2407.19341"}))
    assert result.ok, result.content

    [paper] = list_papers(ot)
    assert paper.title == "Spectral Bounds for Cliques"
    assert paper.year == 2024
    assert paper.abstract == "An abstract."
    assert "arXiv:" not in paper.title
