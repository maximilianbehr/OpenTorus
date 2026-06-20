"""bioRxiv / medRxiv connector (free; biology, medicine preprints).

bioRxiv/medRxiv have no native keyword-search API, so keyword search is served
through the Europe PMC preprint index (the records *are* bioRxiv/medRxiv
preprints, re-tagged by server) — overlaps with Europe PMC are removed by the
shared DOI dedup. The native ``details`` collection feed is also parsed
(``parse_biorxiv``) for date-range acquisition by DOI.
"""

from __future__ import annotations

from opentorus.research.sources.base import (
    LiteratureSource,
    SourceRecord,
    build_url,
    http_get_json,
)
from opentorus.research.sources.europepmc import API as EPMC_API
from opentorus.research.sources.europepmc import parse_europepmc

_PUBLISHER = {"biorxiv": "bioRxiv", "medrxiv": "medRxiv"}


def parse_biorxiv(data: dict, server: str = "biorxiv") -> list[SourceRecord]:
    """Parse the native bioRxiv/medRxiv ``details`` collection feed."""
    records: list[SourceRecord] = []
    for item in data.get("collection") or []:
        date = str(item.get("date") or "")
        year = int(date[:4]) if date[:4].isdigit() else None
        authors = [a.strip() for a in (item.get("authors") or "").split(";") if a.strip()]
        doi = item.get("doi")
        records.append(
            SourceRecord(
                source=server,
                title=item.get("title") or "(untitled)",
                authors=authors,
                year=year,
                venue=_PUBLISHER.get(server, server),
                doi=doi,
                is_open_access=True,
                url=f"https://doi.org/{doi}" if doi else None,
                external_id=doi,
            )
        )
    return records


class BiorxivSource(LiteratureSource):
    name = "biorxiv"
    host = "www.ebi.ac.uk"
    fields = ("bio", "med")

    def __init__(self, server: str = "biorxiv") -> None:
        if server not in _PUBLISHER:
            server = "biorxiv"
        self.server = server
        self.name = server

    def search(self, query: str, limit: int = 10) -> list[SourceRecord]:
        publisher = _PUBLISHER[self.server]
        full_query = f'{query} AND (SRC:"PPR" AND PUBLISHER:"{publisher}")'
        url = build_url(
            EPMC_API,
            {"query": full_query, "format": "json", "pageSize": limit, "resultType": "core"},
        )
        return parse_europepmc(http_get_json(url), source=self.server)
