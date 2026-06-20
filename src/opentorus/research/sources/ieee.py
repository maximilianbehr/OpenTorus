"""IEEE Xplore connector (requires a user-supplied API key).

Metadata is available via the API; full-text access depends on the user's
license and is handled through the institutional path in Milestone 44.
"""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://ieeexploreapi.ieee.org/api/v1/search/articles"


def parse_ieee(data: dict) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for art in data.get("articles", []):
        authors_obj = art.get("authors") or {}
        authors = [a.get("full_name", "") for a in authors_obj.get("authors", [])]
        records.append(
            SourceRecord(
                source="ieee",
                title=art.get("title") or "(untitled)",
                authors=[a for a in authors if a],
                year=art.get("publication_year"),
                venue=art.get("publication_title"),
                doi=art.get("doi"),
                abstract=art.get("abstract") or None,
                is_open_access=str(art.get("access_type", "")).upper() == "OPEN_ACCESS",
                pdf_url=art.get("pdf_url"),
                url=art.get("html_url") or art.get("abstract_url"),
                external_id=str(art.get("article_number")) if art.get("article_number") else None,
                citation_count=art.get("citing_paper_count"),
            )
        )
    return records


class IEEESource(LiteratureSource):
    name = "ieee"
    requires_key = True
    host = "ieeexploreapi.ieee.org"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(
            API,
            {
                "querytext": query,
                "max_records": limit,
                "apikey": self.api_key,
                "format": "json",
            },
        )
        return parse_ieee(http_get_json(url))
