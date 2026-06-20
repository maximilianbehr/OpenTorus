"""Literature source connectors (Phase 13, Milestone 42).

Each source exposes a uniform :class:`LiteratureSource` interface returning
normalized :class:`SourceRecord` results, so the agent loop, the index, and the
graph treat every source the same way. HTTP fetching is separated from response
parsing so connectors are testable offline with canned fixtures.
"""

from opentorus.research.sources.base import LiteratureSource, SourceRecord
from opentorus.research.sources.registry import (
    available_sources,
    search_all,
    sources_for_field,
)

__all__ = [
    "LiteratureSource",
    "SourceRecord",
    "available_sources",
    "search_all",
    "sources_for_field",
]
