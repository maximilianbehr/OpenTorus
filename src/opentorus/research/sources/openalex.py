"""OpenAlex connector (free, no key).

OpenAlex provides rich metadata, citation counts, and open-access links. The
abstract is stored as an inverted index, which we reconstruct into plain text.
"""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)

API = "https://api.openalex.org/works"


def _reconstruct_abstract(inverted: dict | None) -> str | None:
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def _clean_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return doi.replace("https://doi.org/", "").strip() or None


def parse_openalex(data: dict) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for work in data.get("results", []):
        oa = work.get("open_access") or {}
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        authors = [
            (a.get("author") or {}).get("display_name", "") for a in work.get("authorships", [])
        ]
        records.append(
            SourceRecord(
                source="openalex",
                title=work.get("title") or work.get("display_name") or "(untitled)",
                authors=[a for a in authors if a],
                year=work.get("publication_year"),
                venue=source.get("display_name"),
                doi=_clean_doi(work.get("doi")),
                abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
                is_open_access=oa.get("is_oa"),
                pdf_url=oa.get("oa_url"),
                url=work.get("id"),
                external_id=work.get("id"),
                citation_count=work.get("cited_by_count"),
            )
        )
    return records


class OpenAlexSource(LiteratureSource):
    name = "openalex"
    host = "api.openalex.org"

    def __init__(self, contact_email: str | None = None) -> None:
        self.contact_email = contact_email

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(API, {"search": query, "per-page": limit, "mailto": self.contact_email})
        return parse_openalex(http_get_json(url))
