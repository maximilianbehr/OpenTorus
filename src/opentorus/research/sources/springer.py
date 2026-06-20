"""Springer Nature connector (requires a user-supplied API key).

Metadata is always available; full text only for open-access or licensed
content. Licensed full-text retrieval goes through the institutional path in
Milestone 44, not here.
"""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://api.springernature.com/meta/v2/json"


def _first_url(urls: object) -> str | None:
    if isinstance(urls, list) and urls:
        first = urls[0]
        if isinstance(first, dict):
            return first.get("value")
        return str(first)
    if isinstance(urls, str):
        return urls
    return None


def parse_springer(data: dict) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for rec in data.get("records", []):
        creators = [c.get("creator", "") for c in rec.get("creators", [])]
        pub_date = rec.get("publicationDate") or ""
        year = int(pub_date[:4]) if pub_date[:4].isdigit() else None
        is_oa = str(rec.get("openaccess", "")).lower() == "true"
        records.append(
            SourceRecord(
                source="springer",
                title=rec.get("title") or "(untitled)",
                authors=[c for c in creators if c],
                year=year,
                venue=rec.get("publicationName"),
                doi=rec.get("doi"),
                abstract=rec.get("abstract") or None,
                is_open_access=is_oa,
                url=_first_url(rec.get("url")),
                external_id=rec.get("doi"),
            )
        )
    return records


class SpringerSource(LiteratureSource):
    name = "springer"
    requires_key = True
    host = "api.springernature.com"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(API, {"q": query, "p": limit, "api_key": self.api_key})
        return parse_springer(http_get_json(url))
