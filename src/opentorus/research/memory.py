"""Structured project memory stored as per-kind JSONL ledgers.

Memory is intentionally not a vague chat history: each entry has a kind so the
audit trail stays inspectable. Kinds map to files under ``.opentorus/memory/``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl

MemoryKind = Literal["facts", "decisions", "failed_attempts", "hypotheses", "observations"]

VALID_KINDS: tuple[MemoryKind, ...] = (
    "facts",
    "decisions",
    "failed_attempts",
    "hypotheses",
    "observations",
)

_ID_PREFIX = {
    "facts": "FACT",
    "decisions": "DECISION",
    "failed_attempts": "FAILED",
    "hypotheses": "HYP",
    "observations": "OBS",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MemoryEntry(BaseModel):
    id: str
    kind: MemoryKind
    text: str
    created_at: datetime = Field(default_factory=_utcnow)


def memory_dir(workspace_dir: Path) -> Path:
    return workspace_dir / "memory"


def _kind_path(workspace_dir: Path, kind: MemoryKind) -> Path:
    return memory_dir(workspace_dir) / f"{kind}.jsonl"


def add_memory(workspace_dir: Path, kind: MemoryKind, text: str) -> MemoryEntry:
    """Record a memory entry, or return the existing one when the text is identical.

    Writing the same note twice records nothing new, and the ledger is read back as
    "what this run has established" — so a duplicate inflates that count without adding
    knowledge. It is also invisible to every loop guard, because the call *succeeds*:
    one run wrote one and the same observation 364 times, 365 of its 390 actions, and
    nothing anywhere counted it. Returning the original entry makes the repeat a no-op
    the caller can report honestly.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"Unknown memory kind '{kind}'. Valid: {', '.join(VALID_KINDS)}")
    path = _kind_path(workspace_dir, kind)
    existing = read_jsonl(path, MemoryEntry)
    normalized = " ".join(text.split())
    for entry in existing:
        if " ".join(entry.text.split()) == normalized:
            return entry
    entry_id = next_sequential_id(_ID_PREFIX[kind], len(existing))
    entry = MemoryEntry(id=entry_id, kind=kind, text=text)
    append_jsonl(path, entry)
    return entry


def list_memory(workspace_dir: Path, kind: MemoryKind) -> list[MemoryEntry]:
    return read_jsonl(_kind_path(workspace_dir, kind), MemoryEntry)


def rank_entries(
    workspace_dir: Path,
    *,
    limit: int | None = None,
    max_unused_days: int = 30,
    kinds: tuple[MemoryKind, ...] = VALID_KINDS,
    now: datetime | None = None,
) -> list[MemoryEntry]:
    """Ledger entries for the agent's context, ranked by use.

    Order: most citing sessions first, then most recent use (an entry never cited
    ranks by when it was written). An entry gone unused for ``max_unused_days`` (see
    :func:`opentorus.research.memory_index.is_expired`) is left out of the selection —
    it stays in its ledger, nothing is deleted. Failed attempts are always eligible:
    a dead end nobody cited is still a dead end (invariant 5), so it is never aged out.
    """
    from opentorus.research.memory_index import is_expired, rank_key, usage_stats

    stats = usage_stats(workspace_dir)
    moment = now or _utcnow()
    pool: list[MemoryEntry] = []
    for kind in kinds:
        for entry in list_memory(workspace_dir, kind):
            if kind != "failed_attempts" and is_expired(
                stats.get(entry.id), now=moment, max_unused_days=max_unused_days
            ):
                continue
            pool.append(entry)
    pool.sort(key=lambda e: rank_key(e.id, stats, e.created_at))
    return pool if limit is None else pool[:limit]
