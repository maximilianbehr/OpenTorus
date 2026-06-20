"""Europe PMC connector (free; biomedicine, covers PubMed).

Europe PMC indexes PubMed/MEDLINE plus preprints. The REST search returns JSON
under ``resultList.result``.
"""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _authors(item: dict) -> list[str]:
    author_list = (item.get("authorList") or {}).get("author")
    if isinstance(author_list, list) and author_list:
        names = [a.get("fullName") or a.get("lastName") or "" for a in author_list]
        return [n for n in names if n]
    text = item.get("authorString")
    if text:
        return [a.strip() for a in text.split(",") if a.strip()]
    return []


def _pdf_url(item: dict) -> str | None:
    urls = (item.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    for entry in urls:
        if isinstance(entry, dict) and entry.get("documentStyle") == "pdf":
            return entry.get("url")
    return None


def _year(item: dict) -> int | None:
    year = item.get("pubYear")
    try:
        return int(year) if year is not None else None
    except (TypeError, ValueError):
        return None


def _record(item: dict, source: str = "europepmc") -> SourceRecord:
    journal = ((item.get("journalInfo") or {}).get("journal") or {}).get("title")
    return SourceRecord(
        source=source,
        title=item.get("title") or "(untitled)",
        authors=_authors(item),
        year=_year(item),
        venue=journal or item.get("source"),
        doi=item.get("doi"),
        abstract=item.get("abstractText") or None,
        is_open_access=str(item.get("isOpenAccess", "")).upper() == "Y",
        pdf_url=_pdf_url(item),
        url=(
            f"https://europepmc.org/article/{item.get('source')}/{item.get('id')}"
            if item.get("source") and item.get("id")
            else None
        ),
        external_id=item.get("id"),
        citation_count=item.get("citedByCount"),
    )


def parse_europepmc(data: dict, source: str = "europepmc") -> list[SourceRecord]:
    results = (data.get("resultList") or {}).get("result") or []
    return [_record(item, source=source) for item in results]


class EuropePmcSource(LiteratureSource):
    name = "europepmc"
    host = "www.ebi.ac.uk"
    fields = ("bio", "med")

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(
            API,
            {"query": query, "format": "json", "pageSize": limit, "resultType": "core"},
        )
        return parse_europepmc(http_get_json(url))
