"""Offline tests for literature source connectors (Milestone 42).

Parsing is tested against canned API fixtures; no network access occurs. The
registry/degradation behaviour is tested via configuration alone, and
``search_all`` is exercised with a monkeypatched in-memory source.
"""

from __future__ import annotations

import json

import pytest

from opentorus.config import default_config
from opentorus.research.sources import available_sources, search_all
from opentorus.research.sources.arxiv import parse_arxiv
from opentorus.research.sources.base import LiteratureSource, SourceError, SourceRecord
from opentorus.research.sources.crossref import parse_crossref, parse_crossref_single
from opentorus.research.sources.ieee import parse_ieee
from opentorus.research.sources.openalex import parse_openalex
from opentorus.research.sources.semantic_scholar import parse_semantic_scholar
from opentorus.research.sources.springer import parse_springer


def test_parse_openalex_reconstructs_abstract() -> None:
    data = {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "title": "On Toric Varieties",
                "publication_year": 2021,
                "doi": "https://doi.org/10.1/abc",
                "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                "primary_location": {"source": {"display_name": "J. Algebra"}},
                "abstract_inverted_index": {"Hello": [0], "world": [1]},
                "open_access": {"is_oa": True, "oa_url": "https://x/pdf"},
                "cited_by_count": 42,
            }
        ]
    }
    [record] = parse_openalex(data)
    assert record.source == "openalex"
    assert record.title == "On Toric Varieties"
    assert record.doi == "10.1/abc"
    assert record.authors == ["Ada Lovelace"]
    assert record.abstract == "Hello world"
    assert record.is_open_access is True
    assert record.citation_count == 42


def test_parse_arxiv_atom() -> None:
    atom = """<?xml version='1.0'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>http://arxiv.org/abs/2401.01234v2</id>
        <title>Deep   Torus   Learning</title>
        <summary>  A study of   tori.  </summary>
        <published>2024-01-05T00:00:00Z</published>
        <author><name>Grace Hopper</name></author>
        <link title='pdf' href='http://arxiv.org/pdf/2401.01234v2' type='application/pdf'/>
      </entry>
    </feed>"""
    [record] = parse_arxiv(atom)
    assert record.source == "arxiv"
    assert record.title == "Deep Torus Learning"
    assert record.abstract == "A study of tori."
    assert record.arxiv_id == "2401.01234v2"
    assert record.year == 2024
    assert record.is_open_access is True
    assert record.pdf_url.endswith("2401.01234v2")


def test_parse_crossref_strips_jats() -> None:
    data = {
        "message": {
            "items": [
                {
                    "DOI": "10.1/xyz",
                    "title": ["A Result"],
                    "author": [{"given": "Alan", "family": "Turing"}],
                    "container-title": ["Proc. Math"],
                    "issued": {"date-parts": [[2019]]},
                    "abstract": "<jats:p>Concise <b>summary</b>.</jats:p>",
                    "is-referenced-by-count": 7,
                    "URL": "https://doi.org/10.1/xyz",
                }
            ]
        }
    }
    [record] = parse_crossref(data)
    assert record.doi == "10.1/xyz"
    assert record.authors == ["Alan Turing"]
    assert record.year == 2019
    assert record.abstract == "Concise summary."
    assert record.citation_count == 7


def test_parse_crossref_single() -> None:
    data = {"message": {"DOI": "10.2/q", "title": ["Solo"], "issued": {"date-parts": [[2020]]}}}
    record = parse_crossref_single(data)
    assert record is not None
    assert record.doi == "10.2/q"
    assert parse_crossref_single({"message": {}}) is None


def test_parse_semantic_scholar() -> None:
    data = {
        "data": [
            {
                "paperId": "abc123",
                "title": "Spectra",
                "authors": [{"name": "Emmy Noether"}],
                "year": 2018,
                "venue": "Annals",
                "abstract": "About spectra.",
                "externalIds": {"DOI": "10.3/d", "ArXiv": "1801.00001"},
                "openAccessPdf": {"url": "https://x/pdf"},
                "citationCount": 5,
            }
        ]
    }
    [record] = parse_semantic_scholar(data)
    assert record.arxiv_id == "1801.00001"
    assert record.doi == "10.3/d"
    assert record.is_open_access is True
    assert record.external_id == "abc123"


def test_parse_springer() -> None:
    data = {
        "records": [
            {
                "title": "Manifolds",
                "creators": [{"creator": "B. Riemann"}],
                "publicationName": "Springer J.",
                "publicationDate": "2022-03-01",
                "doi": "10.4/spr",
                "abstract": "On manifolds.",
                "openaccess": "true",
                "url": [{"value": "https://link.springer.com/x"}],
            }
        ]
    }
    [record] = parse_springer(data)
    assert record.source == "springer"
    assert record.year == 2022
    assert record.is_open_access is True
    assert record.url == "https://link.springer.com/x"


def test_parse_ieee() -> None:
    data = {
        "articles": [
            {
                "title": "Signals",
                "authors": {"authors": [{"full_name": "C. Shannon"}]},
                "publication_year": 1948,
                "publication_title": "Bell Sys.",
                "doi": "10.5/ie",
                "abstract": "Information.",
                "access_type": "OPEN_ACCESS",
                "article_number": "99",
                "citing_paper_count": 1000,
            }
        ]
    }
    [record] = parse_ieee(data)
    assert record.year == 1948
    assert record.is_open_access is True
    assert record.external_id == "99"
    assert record.citation_count == 1000


def test_available_sources_default_excludes_keyed() -> None:
    config = default_config()
    names = {s.name for s in available_sources(config)}
    # Free, keyless sources are on by default; keyed ones (springer/ieee/ads) stay out.
    assert {"openalex", "arxiv", "crossref", "semantic_scholar"} <= names
    assert names.isdisjoint({"springer", "ieee", "ads"})


def test_springer_ieee_enabled_only_with_key() -> None:
    config = default_config()
    config.tools.literature.springer = True
    config.tools.literature.ieee = True
    # Enabled but unkeyed: must degrade (stay out).
    assert "springer" not in {s.name for s in available_sources(config)}
    assert "ieee" not in {s.name for s in available_sources(config)}
    config.tools.literature.springer_api_key = "k1"
    config.tools.literature.ieee_api_key = "k2"
    names = {s.name for s in available_sources(config)}
    assert {"springer", "ieee"} <= names


def test_disabled_literature_returns_no_sources() -> None:
    config = default_config()
    config.tools.literature.enabled = False
    assert available_sources(config) == []


class _FakeSource(LiteratureSource):
    def __init__(
        self,
        name: str,
        records: list[SourceRecord],
        fail: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self._records = records
        self._fail = fail
        self._error = error

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        if self._error is not None:
            raise self._error
        if self._fail:
            raise SourceError("boom")
        return self._records


def test_search_all_dedupes_and_survives_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    good = _FakeSource(
        "openalex",
        [SourceRecord(source="openalex", title="Dup", doi="10.1/x")],
    )
    dup = _FakeSource(
        "crossref",
        [SourceRecord(source="crossref", title="Dup", doi="10.1/X")],
    )
    broken = _FakeSource("arxiv", [], fail=True)
    monkeypatch.setattr(
        "opentorus.research.sources.registry.available_sources",
        lambda config: [good, dup, broken],
    )
    config = default_config()
    results = search_all(config, "anything")
    assert len(results) == 1  # case-insensitive DOI dedupe; broken source skipped


def test_benign_source_failures_do_not_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Missing-key/rate-limit/no-result failures stay quiet (no WARNING noise)."""
    rate_limited = _FakeSource(
        "semantic_scholar", [], error=SourceError("HTTP 429 ...", status=429)
    )
    not_found = _FakeSource("zbmath", [], error=SourceError("HTTP 404 ...", status=404))
    needs_key = _FakeSource("ieee", [], error=SourceError("HTTP 403 ...", status=403))
    monkeypatch.setattr(
        "opentorus.research.sources.registry.available_sources",
        lambda config: [rate_limited, not_found, needs_key],
    )
    with caplog.at_level("DEBUG", logger="opentorus"):
        results = search_all(default_config(), "anything")
    assert results == []
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert all(r.levelname == "DEBUG" for r in caplog.records)


def test_unexpected_source_error_is_warned(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-SourceError bug surfaces as a WARNING; a 5xx is only INFO."""
    crashing = _FakeSource("openalex", [], error=ValueError("bug"))
    server_error = _FakeSource("crossref", [], error=SourceError("HTTP 500 ...", status=500))
    monkeypatch.setattr(
        "opentorus.research.sources.registry.available_sources",
        lambda config: [crashing, server_error],
    )
    with caplog.at_level("DEBUG", logger="opentorus"):
        search_all(default_config(), "anything")
    levels = {r.levelname for r in caplog.records}
    assert "WARNING" in levels  # the ValueError bug
    assert any(r.levelname == "INFO" for r in caplog.records)  # the 5xx


def test_source_record_serializable() -> None:
    record = SourceRecord(source="arxiv", title="T", authors=["A"])
    assert json.loads(record.model_dump_json())["title"] == "T"
