"""NASA ADS connector (requires a user-supplied API token; astro/physics).

The ADS API needs a bearer token. Records come from ``response.docs``.
"""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://api.adsabs.harvard.edu/v1/search/query"
_FIELDS = "title,author,year,pub,doi,bibcode,citation_count,abstract"


def _first(value) -> str | None:  # noqa: ANN001
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value is not None else None


def _year(doc: dict) -> int | None:
    year = doc.get("year")
    try:
        return int(year) if year is not None else None
    except (TypeError, ValueError):
        return None


def parse_ads(data: dict) -> list[SourceRecord]:
    docs = (data.get("response") or {}).get("docs") or []
    records: list[SourceRecord] = []
    for doc in docs:
        records.append(
            SourceRecord(
                source="ads",
                title=_first(doc.get("title")) or "(untitled)",
                authors=[a for a in (doc.get("author") or []) if a],
                year=_year(doc),
                venue=doc.get("pub"),
                doi=_first(doc.get("doi")),
                abstract=doc.get("abstract") or None,
                url=(
                    f"https://ui.adsabs.harvard.edu/abs/{doc.get('bibcode')}"
                    if doc.get("bibcode")
                    else None
                ),
                external_id=doc.get("bibcode"),
                citation_count=doc.get("citation_count"),
            )
        )
    return records


class AdsSource(LiteratureSource):
    name = "ads"
    requires_key = True
    host = "api.adsabs.harvard.edu"
    fields = ("astro", "physics")

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(API, {"q": query, "rows": limit, "fl": _FIELDS})
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return parse_ads(http_get_json(url, headers=headers))
