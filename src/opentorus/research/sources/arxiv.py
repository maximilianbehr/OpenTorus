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

    def lookup_id(self, arxiv_id: str) -> SourceRecord | None:
        """The record for one arXiv id, or ``None`` when the API knows no such paper.

        The counterpart to :meth:`CrossrefSource.lookup_doi`. ``paper_fetch`` had no
        arXiv equivalent, so it synthesised ``title=f"arXiv:{id}"`` and downloaded the
        PDF: every arXiv paper landed carrying its own id as its title, with no year,
        authors or abstract, while a DOI fetched right next to it got all of them.
        """
        url = build_url(API, {"id_list": arxiv_id, "max_results": 1})
        records = parse_arxiv(http_get_text(url))
        if not records:
            return None
        # An unknown id still yields one entry, but it is the API's error document:
        # its id is ``.../api/errors#…`` rather than an ``/abs/`` link, so no arXiv id
        # is parsed out of it. That is a miss, not a paper.
        return records[0] if records[0].arxiv_id else None
