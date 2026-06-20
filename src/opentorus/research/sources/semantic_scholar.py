"""Semantic Scholar connector (free; optional key raises rate limits)."""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,authors,year,venue,abstract,externalIds,openAccessPdf,citationCount"


def parse_semantic_scholar(data: dict) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for paper in data.get("data", []):
        external = paper.get("externalIds") or {}
        oa = paper.get("openAccessPdf") or {}
        authors = [a.get("name", "") for a in paper.get("authors", [])]
        records.append(
            SourceRecord(
                source="semantic_scholar",
                title=paper.get("title") or "(untitled)",
                authors=[a for a in authors if a],
                year=paper.get("year"),
                venue=paper.get("venue") or None,
                doi=external.get("DOI"),
                arxiv_id=external.get("ArXiv"),
                abstract=paper.get("abstract"),
                is_open_access=bool(oa.get("url")) or None,
                pdf_url=oa.get("url"),
                external_id=paper.get("paperId"),
                citation_count=paper.get("citationCount"),
            )
        )
    return records


class SemanticScholarSource(LiteratureSource):
    name = "semantic_scholar"
    host = "api.semanticscholar.org"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(API, {"query": query, "limit": limit, "fields": _FIELDS})
        headers = {"x-api-key": self.api_key} if self.api_key else None
        return parse_semantic_scholar(http_get_json(url, headers=headers))
