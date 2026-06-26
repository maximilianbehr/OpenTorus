"""Resolve enabled literature sources from configuration.

Free sources are built whenever enabled; Springer/IEEE are built only when both
enabled *and* keyed, so a missing key disables just that source rather than
failing the search.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opentorus.config import Config
from opentorus.research.sources.ads import AdsSource
from opentorus.research.sources.arxiv import ArxivSource
from opentorus.research.sources.base import LiteratureSource, SourceError, SourceRecord
from opentorus.research.sources.biorxiv import BiorxivSource

if TYPE_CHECKING:
    from opentorus.research.egress import EgressGuard
from opentorus.research.sources.crossref import CrossrefSource
from opentorus.research.sources.dblp import DblpSource
from opentorus.research.sources.europepmc import EuropePmcSource
from opentorus.research.sources.ieee import IEEESource
from opentorus.research.sources.openalex import OpenAlexSource
from opentorus.research.sources.semantic_scholar import SemanticScholarSource
from opentorus.research.sources.springer import SpringerSource
from opentorus.research.sources.zbmath import ZbmathSource

logger = logging.getLogger("opentorus")

# HTTP statuses that are *expected* when searching keyless/free sources and so
# must not produce a noisy warning: missing/invalid API key (401/403), no
# matching results (404, e.g. zbMATH), and rate limiting (429). One source being
# unavailable for these reasons never aborts the search.
_BENIGN_STATUS = frozenset({401, 403, 404, 429})


def available_sources(config: Config) -> list[LiteratureSource]:
    lit = config.tools.literature
    if not lit.enabled:
        return []
    sources: list[LiteratureSource] = []
    if lit.openalex:
        sources.append(OpenAlexSource(contact_email=lit.contact_email))
    if lit.arxiv:
        sources.append(ArxivSource())
    if lit.crossref:
        sources.append(CrossrefSource(contact_email=lit.contact_email))
    if lit.semantic_scholar:
        sources.append(SemanticScholarSource(api_key=lit.semantic_scholar_api_key))
    if lit.dblp:
        sources.append(DblpSource())
    if lit.zbmath:
        sources.append(ZbmathSource())
    if lit.europepmc:
        sources.append(EuropePmcSource())
    if lit.biorxiv:
        sources.append(BiorxivSource("biorxiv"))
        sources.append(BiorxivSource("medrxiv"))
    if lit.springer and lit.springer_api_key:
        sources.append(SpringerSource(api_key=lit.springer_api_key))
    if lit.ieee and lit.ieee_api_key:
        sources.append(IEEESource(api_key=lit.ieee_api_key))
    if lit.ads and lit.ads_api_key:
        sources.append(AdsSource(api_key=lit.ads_api_key))
    return sources


def sources_for_field(config: Config, field: str | None) -> list[LiteratureSource]:
    """Pick relevant sources for a topic's field hint (e.g. ``"math"``).

    General-purpose sources (no field hint) are always included; field-specific
    sources join only when their hint matches. An unknown/empty field returns all
    enabled sources unchanged.
    """
    enabled = available_sources(config)
    if not field:
        return enabled
    wanted = field.strip().lower()
    return [s for s in enabled if not s.fields or wanted in s.fields]


def search_all(
    config: Config,
    query: str,
    limit: int = 10,
    sources: list[str] | None = None,
    egress: EgressGuard | None = None,
) -> list[SourceRecord]:
    """Search every enabled source (optionally filtered by name) and merge results.

    A source that errors is skipped with a warning so one failure never aborts
    the whole search. When an ``egress`` guard is supplied, each source's host is
    authorized first; a blocked or unconfirmed host skips just that source.
    Results are deduplicated by DOI then arXiv id.
    """
    from opentorus.research.egress import EgressBlocked
    from opentorus.research.sources.base import normalize_search_query

    # Strip Google-style operators the connectors cannot honor (notably arXiv, where a
    # leading '-' is read as include, so an exclusion backfires into millions of hits).
    query = normalize_search_query(query) or query

    chosen = available_sources(config)
    if sources:
        wanted = set(sources)
        chosen = [s for s in chosen if s.name in wanted]

    merged: list[SourceRecord] = []
    for source in chosen:
        if egress is not None and source.host:
            try:
                egress.authorize(source.host)
            except EgressBlocked as exc:
                logger.warning("Egress to source '%s' denied: %s", source.name, exc)
                continue
        try:
            merged.extend(source.search(query, limit=limit))
        except SourceError as exc:
            if exc.status in _BENIGN_STATUS:
                # Expected when a source needs a key, is rate limited, or simply
                # has no results — keep quiet by default (visible with --debug).
                logger.debug(
                    "Literature source '%s' unavailable (HTTP %s): %s",
                    source.name,
                    exc.status,
                    exc,
                )
            else:
                # Other failures (timeouts, 5xx, unreachable host) are not fatal —
                # other sources still answer — so surface them only at --verbose.
                logger.info("Literature source '%s' failed: %s", source.name, exc)
        except Exception as exc:  # noqa: BLE001 - resilience: never abort the whole search
            logger.warning(
                "Literature source '%s' raised an unexpected error: %s",
                source.name,
                exc,
            )
    return _dedupe(merged)


def _dedupe(records: list[SourceRecord]) -> list[SourceRecord]:
    seen: set[str] = set()
    unique: list[SourceRecord] = []
    for record in records:
        key = (record.doi or "").lower() or (record.arxiv_id or "").lower()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(record)
    return unique
