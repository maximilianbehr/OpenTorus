"""Offline tests for the additional literature connectors (Milestone 70).

Each connector parses canned fixtures into ``SourceRecord``s; no network access
occurs. Field-hint selection, cross-source dedup, and keyed-source degradation
are covered via configuration alone.
"""

from __future__ import annotations

from opentorus.config import default_config
from opentorus.research.sources import (
    available_sources,
    search_all,
    sources_for_field,
)
from opentorus.research.sources.ads import parse_ads
from opentorus.research.sources.base import LiteratureSource, SourceRecord
from opentorus.research.sources.biorxiv import parse_biorxiv
from opentorus.research.sources.dblp import parse_dblp
from opentorus.research.sources.europepmc import parse_europepmc
from opentorus.research.sources.zbmath import parse_zbmath


def test_parse_dblp() -> None:
    data = {
        "result": {
            "hits": {
                "hit": [
                    {
                        "@id": "12345",
                        "info": {
                            "title": "On Lattices in Polynomial Time.",
                            "authors": {
                                "author": [
                                    {"text": "Ada Lovelace"},
                                    {"text": "Alan Turing"},
                                ]
                            },
                            "venue": "STOC",
                            "year": "2021",
                            "doi": "10.1/dblp",
                            "ee": "https://doi.org/10.1/dblp",
                        },
                    }
                ]
            }
        }
    }
    [record] = parse_dblp(data)
    assert record.source == "dblp"
    assert record.title == "On Lattices in Polynomial Time"
    assert record.authors == ["Ada Lovelace", "Alan Turing"]
    assert record.year == 2021
    assert record.doi == "10.1/dblp"


def test_parse_dblp_single_author_as_dict() -> None:
    data = {
        "result": {
            "hits": {
                "hit": {
                    "info": {
                        "title": "Solo Work",
                        "authors": {"author": {"text": "Grace Hopper"}},
                        "year": "2010",
                    }
                }
            }
        }
    }
    [record] = parse_dblp(data)
    assert record.authors == ["Grace Hopper"]


def test_parse_zbmath() -> None:
    data = {
        "result": [
            {
                "id": 7777,
                "title": {"title": "Toric Degenerations"},
                "contributors": {"authors": [{"name": "B. Riemann"}]},
                "year": 2019,
                "source": {"series": "Math. Ann."},
                "links": [{"type": "doi", "identifier": "10.2/zb"}],
            }
        ]
    }
    [record] = parse_zbmath(data)
    assert record.source == "zbmath"
    assert record.title == "Toric Degenerations"
    assert record.authors == ["B. Riemann"]
    assert record.year == 2019
    assert record.venue == "Math. Ann."
    assert record.doi == "10.2/zb"
    assert record.external_id == "7777"


def test_parse_zbmath_series_as_list() -> None:
    # The live API returns ``source.series`` as a list of objects, not a string;
    # a bad coercion previously raised a ValidationError that crashed the REPL.
    data = {
        "result": [
            {
                "id": 1234,
                "title": {"title": "On the Crouzeix Conjecture"},
                "source": {
                    "series": [
                        {
                            "acronym": None,
                            "issn": [],
                            "title": "Linear Algebra Appl.",
                            "year": "2017",
                        }
                    ]
                },
            }
        ]
    }
    [record] = parse_zbmath(data)
    assert record.venue == "Linear Algebra Appl."


def test_parse_zbmath_handles_missing_venue() -> None:
    data = {"result": [{"id": 9, "title": "No Source", "source": {"series": []}}]}
    [record] = parse_zbmath(data)
    assert record.venue is None


def test_parse_europepmc() -> None:
    data = {
        "resultList": {
            "result": [
                {
                    "id": "PMC1",
                    "source": "MED",
                    "title": "On Spectra",
                    "authorString": "Noether E, Hilbert D",
                    "pubYear": "2018",
                    "journalInfo": {"journal": {"title": "Cell"}},
                    "doi": "10.3/epmc",
                    "abstractText": "About spectra.",
                    "isOpenAccess": "Y",
                    "citedByCount": 11,
                    "fullTextUrlList": {
                        "fullTextUrl": [{"documentStyle": "pdf", "url": "https://x/pdf"}]
                    },
                }
            ]
        }
    }
    [record] = parse_europepmc(data)
    assert record.source == "europepmc"
    assert record.authors == ["Noether E", "Hilbert D"]
    assert record.year == 2018
    assert record.venue == "Cell"
    assert record.doi == "10.3/epmc"
    assert record.is_open_access is True
    assert record.pdf_url == "https://x/pdf"
    assert record.citation_count == 11


def test_parse_biorxiv_collection() -> None:
    data = {
        "collection": [
            {
                "doi": "10.1101/2024.01.01.123456",
                "title": "A Preprint",
                "authors": "Curie M; Bohr N",
                "date": "2024-01-01",
            }
        ]
    }
    [record] = parse_biorxiv(data, server="biorxiv")
    assert record.source == "biorxiv"
    assert record.authors == ["Curie M", "Bohr N"]
    assert record.year == 2024
    assert record.is_open_access is True
    assert record.doi == "10.1101/2024.01.01.123456"


def test_parse_ads() -> None:
    data = {
        "response": {
            "docs": [
                {
                    "title": ["A Galaxy Survey"],
                    "author": ["Hubble E."],
                    "year": "1929",
                    "pub": "ApJ",
                    "doi": ["10.4/ads"],
                    "bibcode": "1929ApJ....X",
                    "citation_count": 9001,
                }
            ]
        }
    }
    [record] = parse_ads(data)
    assert record.source == "ads"
    assert record.title == "A Galaxy Survey"
    assert record.year == 1929
    assert record.doi == "10.4/ads"
    assert record.external_id == "1929ApJ....X"
    assert record.citation_count == 9001


def test_default_sources_include_free_field_connectors() -> None:
    config = default_config()
    names = {s.name for s in available_sources(config)}
    assert {"dblp", "zbmath"} <= names
    # Biomedical servers are off by default (OpenTorus targets open math problems).
    assert {"europepmc", "biorxiv", "medrxiv"}.isdisjoint(names)
    # Keyed sources stay out without a key.
    assert "ads" not in names


def test_biomedical_sources_enable_when_configured() -> None:
    config = default_config()
    config.tools.literature.europepmc = True
    config.tools.literature.biorxiv = True
    names = {s.name for s in available_sources(config)}
    assert {"europepmc", "biorxiv", "medrxiv"} <= names


def test_ads_enabled_only_with_key() -> None:
    config = default_config()
    config.tools.literature.ads = True
    assert "ads" not in {s.name for s in available_sources(config)}
    config.tools.literature.ads_api_key = "tok"
    assert "ads" in {s.name for s in available_sources(config)}


def test_field_hint_filters_sources() -> None:
    config = default_config()
    math = {s.name for s in sources_for_field(config, "math")}
    # zbMATH (math) is in; dblp (cs) and europepmc (bio) are out; general stay in.
    assert "zbmath" in math
    assert "dblp" not in math
    assert "europepmc" not in math
    assert "openalex" in math  # general-purpose, no field hint
    cs = {s.name for s in sources_for_field(config, "cs")}
    assert "dblp" in cs
    assert "zbmath" not in cs
    # No/unknown field returns everything enabled.
    assert {s.name for s in sources_for_field(config, None)} == {
        s.name for s in available_sources(config)
    }


class _FakeSource(LiteratureSource):
    def __init__(self, name: str, records: list[SourceRecord]) -> None:
        self.name = name
        self._records = records

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        return self._records


def test_dedup_across_overlapping_sources(monkeypatch) -> None:  # noqa: ANN001
    epmc = _FakeSource(
        "europepmc",
        [SourceRecord(source="europepmc", title="Shared", doi="10.1101/abc")],
    )
    bio = _FakeSource(
        "biorxiv",
        [SourceRecord(source="biorxiv", title="Shared", doi="10.1101/ABC")],
    )
    monkeypatch.setattr(
        "opentorus.research.sources.registry.available_sources",
        lambda config: [epmc, bio],
    )
    results = search_all(default_config(), "anything")
    assert len(results) == 1  # case-insensitive DOI dedup removes the overlap
