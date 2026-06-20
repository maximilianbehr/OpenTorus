"""arXiv connector (free, full-text PDFs).

Uses the arXiv Atom API. Responses are XML, parsed with the standard library.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_text,
)

API = "http://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


def _arxiv_id(entry_id: str) -> str | None:
    # entry id looks like http://arxiv.org/abs/2401.01234v2
    if "/abs/" not in entry_id:
        return None
    return entry_id.rsplit("/abs/", 1)[1] or None


def parse_arxiv(atom_xml: str) -> list[SourceRecord]:
    root = ET.fromstring(atom_xml)
    records: list[SourceRecord] = []
    for entry in root.findall(f"{_ATOM}entry"):
        entry_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        summary = " ".join((entry.findtext(f"{_ATOM}summary") or "").split()) or None
        published = entry.findtext(f"{_ATOM}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            (a.findtext(f"{_ATOM}name") or "").strip() for a in entry.findall(f"{_ATOM}author")
        ]
        pdf_url = None
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")
        records.append(
            SourceRecord(
                source="arxiv",
                title=title or "(untitled)",
                authors=[a for a in authors if a],
                year=year,
                venue="arXiv",
                arxiv_id=_arxiv_id(entry_id),
                abstract=summary,
                is_open_access=True,
                pdf_url=pdf_url,
                url=entry_id or None,
                external_id=_arxiv_id(entry_id),
            )
        )
    return records


class ArxivSource(LiteratureSource):
    name = "arxiv"
    host = "export.arxiv.org"

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        url = build_url(
            API,
            {"search_query": f"all:{query}", "start": 0, "max_results": limit},
        )
        return parse_arxiv(http_get_text(url))
