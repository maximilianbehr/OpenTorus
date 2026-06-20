"""Searchable research journal (Milestone 54).

Each autonomous research iteration appends one inspectable ``JOURNAL-*`` entry:
the goal it pursued, the actions taken, the evidence produced, the affected claim
and its status, and the proposed next step. The journal composes with the action
log, session replay (M19), and usage ledger (M31) to make long investigations
auditable and faithfully resumable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JournalEntry(BaseModel):
    id: str
    investigation: str
    iteration: int
    goal: str = ""
    actions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    claim_id: str | None = None
    claim_status: str | None = None
    next_step: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


def journal_path(ot_dir: Path) -> Path:
    return ot_dir / "journal" / "journal.jsonl"


def list_entries(ot_dir: Path, investigation: str | None = None) -> list[JournalEntry]:
    entries = read_jsonl(journal_path(ot_dir), JournalEntry)
    if investigation is not None:
        return [e for e in entries if e.investigation == investigation]
    return entries


def add_entry(ot_dir: Path, entry: JournalEntry) -> JournalEntry:
    existing = read_jsonl(journal_path(ot_dir), JournalEntry)
    entry.id = next_sequential_id("JOURNAL", len(existing))
    append_jsonl(journal_path(ot_dir), entry)
    return entry


def search_entries(ot_dir: Path, query: str) -> list[JournalEntry]:
    """Case-insensitive substring search across an entry's text fields."""
    q = query.strip().lower()
    if not q:
        return list_entries(ot_dir)
    matches: list[JournalEntry] = []
    for entry in list_entries(ot_dir):
        haystack = " ".join(
            [
                entry.investigation,
                entry.goal,
                entry.next_step,
                entry.claim_id or "",
                entry.claim_status or "",
                " ".join(entry.actions),
            ]
        ).lower()
        if q in haystack:
            matches.append(entry)
    return matches
