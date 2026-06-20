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
    if kind not in VALID_KINDS:
        raise ValueError(f"Unknown memory kind '{kind}'. Valid: {', '.join(VALID_KINDS)}")
    path = _kind_path(workspace_dir, kind)
    existing = read_jsonl(path, MemoryEntry)
    entry_id = next_sequential_id(_ID_PREFIX[kind], len(existing))
    entry = MemoryEntry(id=entry_id, kind=kind, text=text)
    append_jsonl(path, entry)
    return entry


def list_memory(workspace_dir: Path, kind: MemoryKind) -> list[MemoryEntry]:
    return read_jsonl(_kind_path(workspace_dir, kind), MemoryEntry)
