"""zbMATH Open connector (free; mathematics).

zbMATH Open exposes an open REST API for mathematical literature. Records are
normalized from the document search response. (MathSciNet, the subscription
sibling, would slot in here behind a key — but is not bundled.)
"""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://api.zbmath.org/v1/document/_search"


def _authors(doc: dict) -> list[str]:
    contributors = doc.get("contributors") or {}
    authors = contributors.get("authors") or []
    names: list[str] = []
    for a in authors:
        name = a.get("name") if isinstance(a, dict) else str(a)
        if name:
            names.append(name)
    return names


def _title(doc: dict) -> str:
    title = doc.get("title")
    if isinstance(title, dict):
        return title.get("title") or "(untitled)"
    return title or "(untitled)"


def _doi(doc: dict) -> str | None:
    links = doc.get("links") or []
    for link in links:
        if isinstance(link, dict) and (link.get("type") or "").lower() == "doi":
            return link.get("identifier") or link.get("url")
    return doc.get("doi")


def _year(doc: dict) -> int | None:
    year = doc.get("year")
    try:
        return int(year) if year is not None else None
    except (TypeError, ValueError):
        return None


def _series_title(item: object) -> str | None:
    """Pull a human-readable name out of one ``series`` entry."""
    if isinstance(item, dict):
        for key in ("title", "short_title", "acronym"):
            value = item.get(key)
            if value:
                return str(value)
        return None
    if isinstance(item, str) and item:
        return item
    return None


def _venue(doc: dict) -> str | None:
    """Normalize zbMATH's ``source.series`` into a venue string.

    The API returns ``series`` as a list of objects (occasionally a single
    object or a bare string), so we coerce whatever shape we get into a name.
    """
    source_obj = doc.get("source")
    if not isinstance(source_obj, dict):
        return None
    series = source_obj.get("series")
    if isinstance(series, list):
        for item in series:
            title = _series_title(item)
            if title:
                return title
        return None
    return _series_title(series)


def parse_zbmath(data: dict) -> list[SourceRecord]:
    results = data.get("result") or data.get("results") or []
    records: list[SourceRecord] = []
    for doc in results:
        venue = _venue(doc)
        records.append(
            SourceRecord(
                source="zbmath",
                title=_title(doc),
                authors=_authors(doc),
                year=_year(doc),
                venue=venue,
                doi=_doi(doc),
                external_id=str(doc.get("id")) if doc.get("id") is not None else None,
            )
        )
    return records


class ZbmathSource(LiteratureSource):
    name = "zbmath"
    host = "api.zbmath.org"
    fields = ("math",)

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(API, {"search_string": query, "results_per_page": limit})
        return parse_zbmath(http_get_json(url))
