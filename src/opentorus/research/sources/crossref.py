"""Crossref connector (free).

Crossref is the canonical DOI registry; useful for metadata and reference lists.
"""

from __future__ import annotations

import re

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://api.crossref.org/works"


def _first(values: list | None) -> str | None:
    if values and isinstance(values, list):
        return str(values[0])
    return None


def _author_names(authors: list | None) -> list[str]:
    names: list[str] = []
    for a in authors or []:
        given = a.get("given", "")
        family = a.get("family", "")
        full = f"{given} {family}".strip()
        if full:
            names.append(full)
    return names


def _year(item: dict) -> int | None:
    issued = item.get("issued") or {}
    parts = issued.get("date-parts") or []
    if parts and parts[0] and isinstance(parts[0][0], int):
        return parts[0][0]
    return None


def _clean_abstract(abstract: str | None) -> str | None:
    if not abstract:
        return None
    # Crossref abstracts are JATS XML; strip tags for a plain summary.
    return re.sub(r"<[^>]+>", "", abstract).strip() or None


def _to_record(item: dict) -> SourceRecord:
    return SourceRecord(
        source="crossref",
        title=_first(item.get("title")) or "(untitled)",
        authors=_author_names(item.get("author")),
        year=_year(item),
        venue=_first(item.get("container-title")),
        doi=item.get("DOI"),
        abstract=_clean_abstract(item.get("abstract")),
        url=item.get("URL"),
        external_id=item.get("DOI"),
        citation_count=item.get("is-referenced-by-count"),
    )


def parse_crossref(data: dict) -> list[SourceRecord]:
    message = data.get("message") or {}
    return [_to_record(item) for item in message.get("items", [])]


def parse_crossref_single(data: dict) -> SourceRecord | None:
    message = data.get("message")
    if isinstance(message, dict) and message.get("DOI"):
        return _to_record(message)
    return None


class CrossrefSource(LiteratureSource):
    name = "crossref"
    host = "api.crossref.org"

    def __init__(self, contact_email: str | None = None) -> None:
        self.contact_email = contact_email

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(API, {"query": query, "rows": limit, "mailto": self.contact_email})
        return parse_crossref(http_get_json(url))

    def lookup_doi(self, doi: str) -> SourceRecord | None:
        url = build_url(f"{API}/{doi}", {"mailto": self.contact_email})
        return parse_crossref_single(http_get_json(url))
