"""DBLP connector (free; computer science).

DBLP indexes CS publications. The search API returns JSON under
``result.hits.hit[].info``.
"""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://dblp.org/search/publ/api"


def _authors(info: dict) -> list[str]:
    authors = (info.get("authors") or {}).get("author")
    if isinstance(authors, dict):
        authors = [authors]
    names: list[str] = []
    for a in authors or []:
        text = a.get("text") if isinstance(a, dict) else str(a)
        if text:
            names.append(text)
    return names


def _year(info: dict) -> int | None:
    year = info.get("year")
    try:
        return int(year) if year is not None else None
    except (TypeError, ValueError):
        return None


def parse_dblp(data: dict) -> list[SourceRecord]:
    hits = ((data.get("result") or {}).get("hits") or {}).get("hit") or []
    if isinstance(hits, dict):
        hits = [hits]
    records: list[SourceRecord] = []
    for hit in hits:
        info = hit.get("info") or {}
        records.append(
            SourceRecord(
                source="dblp",
                title=(info.get("title") or "(untitled)").rstrip("."),
                authors=_authors(info),
                year=_year(info),
                venue=info.get("venue"),
                doi=info.get("doi"),
                url=info.get("ee") or info.get("url"),
                external_id=hit.get("@id") or info.get("key"),
            )
        )
    return records


class DblpSource(LiteratureSource):
    name = "dblp"
    host = "dblp.org"
    fields = ("cs",)

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(API, {"q": query, "h": limit, "format": "json"})
        return parse_dblp(http_get_json(url))
