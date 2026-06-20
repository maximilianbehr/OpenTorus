"""Cross-workspace knowledge base (Milestone 73).

An opt-in, user-level store (``~/.opentorus/kb/``) that papers, notes, and
citation edges are *promoted* into so they can be reused across investigations.
Three disciplines hold:

* **Deduplication** by DOI / arXiv id, then content hash — the same work is
  stored once even when promoted from several workspaces.
* **Strict provenance** — every entry keeps its origin workspace and artifact id,
  so nothing becomes "truth" merely by being copied. Statuses are never imported.
* **Staleness** — entries carry a ``last_checked`` timestamp; a scheduler surfaces
  entries due for re-checking. Re-verification runs as ordinary evidence in a
  workspace (never an automatic upgrade here).

The KB is plain JSONL + files, inspectable and queryable via the same BM25 used
by the in-workspace index (M46).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl, rewrite_jsonl

KBEntryKind = Literal["paper", "note", "citation"]
DEFAULT_STALENESS_DAYS = 90


def _utcnow() -> datetime:
    return datetime.now(UTC)


class KBEntry(BaseModel):
    id: str
    kind: KBEntryKind
    # Dedup keys (papers/notes).
    doi: str | None = None
    arxiv_id: str | None = None
    content_hash: str | None = None
    title: str | None = None
    text: str = ""
    note_path: str | None = None
    # Citation edges (kind == "citation").
    citing_key: str | None = None
    cited_key: str | None = None
    relation: str | None = None
    # Strict provenance: where this entry came from.
    origin_workspace: str | None = None
    origin_id: str | None = None
    promoted_at: datetime = Field(default_factory=_utcnow)
    last_checked: datetime = Field(default_factory=_utcnow)


def kb_root(kb_dir: Path | None = None) -> Path:
    """Resolve the KB directory: explicit arg, then ``$OPENTORUS_KB_DIR``, then ~."""
    if kb_dir is not None:
        return kb_dir
    env = os.environ.get("OPENTORUS_KB_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".opentorus" / "kb"


def _entries_path(kb_dir: Path) -> Path:
    return kb_root(kb_dir) / "entries.jsonl"


def list_kb_entries(kb_dir: Path | None = None) -> list[KBEntry]:
    return read_jsonl(_entries_path(kb_root(kb_dir)), KBEntry)


def _dedup_key(doi: str | None, arxiv_id: str | None, content_hash: str | None) -> str | None:
    return (
        (doi or "").lower().strip()
        or (arxiv_id or "").lower().strip()
        or (content_hash or "").lower().strip()
        or None
    )


def _find_paper_dup(entries: list[KBEntry], entry: KBEntry) -> KBEntry | None:
    key = _dedup_key(entry.doi, entry.arxiv_id, entry.content_hash)
    if key is None:
        return None
    for existing in entries:
        if existing.kind != "paper":
            continue
        if _dedup_key(existing.doi, existing.arxiv_id, existing.content_hash) == key:
            return existing
    return None


def promote_paper(
    ot_dir: Path, paper_id: str, *, kb_dir: Path | None = None
) -> tuple[KBEntry, bool]:
    """Promote a workspace paper (and its note, if any) into the KB.

    Returns ``(entry, created)``. ``created`` is ``False`` when the paper already
    exists in the KB by DOI/arXiv id or content hash — the existing entry is
    returned unchanged (no duplicate, no status import).
    """
    from opentorus.research.papers import get_paper

    paper = get_paper(ot_dir, paper_id)
    if paper is None:
        raise OpenTorusError(f"No paper with id '{paper_id}' in this workspace.")

    root = kb_root(kb_dir)
    entries = read_jsonl(_entries_path(root), KBEntry)

    text = paper.title or paper.source or ""
    if paper.abstract:
        text = f"{text}\n{paper.abstract}"

    candidate = KBEntry(
        id="",
        kind="paper",
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        content_hash=paper.sha256,
        title=paper.title,
        text=text,
        origin_workspace=str(ot_dir),
        origin_id=paper.id,
    )
    dup = _find_paper_dup(entries, candidate)
    if dup is not None:
        return dup, False

    candidate.id = next_sequential_id("KB-PAPER", sum(1 for e in entries if e.kind == "paper"))

    # Copy the reading note (text only) into the KB to make it self-contained.
    if paper.note_path:
        note_src = ot_dir / paper.note_path
        if note_src.is_file():
            notes_dir = root / "notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            note_dest = notes_dir / f"{candidate.id}.md"
            note_dest.write_text(note_src.read_text(encoding="utf-8"), encoding="utf-8")
            candidate.note_path = str(note_dest.relative_to(root))

    append_jsonl(_entries_path(root), candidate)
    return candidate, True


def promote_citations(ot_dir: Path, *, kb_dir: Path | None = None) -> list[KBEntry]:
    """Promote ``cites``/``derived_from`` edges between papers already in the KB.

    Both endpoints must be promoted (matched by origin workspace + id) and the
    edge is deduplicated, so citation provenance is preserved without inventing
    links between works the KB does not hold.
    """
    from opentorus.research.graph import list_edges

    root = kb_root(kb_dir)
    entries = read_jsonl(_entries_path(root), KBEntry)
    by_origin = {
        (e.origin_workspace, e.origin_id): e for e in entries if e.kind == "paper" and e.origin_id
    }
    existing_edges = {
        (e.citing_key, e.cited_key, e.relation) for e in entries if e.kind == "citation"
    }

    created: list[KBEntry] = []
    for edge in list_edges(ot_dir):
        if edge.relation not in ("cites", "derived_from"):
            continue
        citing = by_origin.get((str(ot_dir), edge.source_id))
        cited = by_origin.get((str(ot_dir), edge.target_id))
        if citing is None or cited is None:
            continue
        triple = (citing.id, cited.id, edge.relation)
        if triple in existing_edges:
            continue
        entry = KBEntry(
            id=next_sequential_id(
                "KB-CITE", sum(1 for e in entries if e.kind == "citation") + len(created)
            ),
            kind="citation",
            citing_key=citing.id,
            cited_key=cited.id,
            relation=edge.relation,
            origin_workspace=str(ot_dir),
            origin_id=edge.id,
        )
        append_jsonl(_entries_path(root), entry)
        existing_edges.add(triple)
        created.append(entry)
    return created


def _bm25(query: str, docs: list[str]) -> list[float]:
    from opentorus.research.index import _bm25_scores, _tokenize

    return _bm25_scores(_tokenize(query), [_tokenize(d) for d in docs])


def query_kb(query: str, k: int = 5, *, kb_dir: Path | None = None) -> list[tuple[KBEntry, float]]:
    """Search the KB (papers + notes) by BM25, reusing the M46 scorer."""
    entries = [e for e in list_kb_entries(kb_dir) if e.kind in ("paper", "note")]
    if not entries:
        return []
    docs = [f"{e.title or ''} {e.text}" for e in entries]
    scores = _bm25(query, docs)
    ranked = sorted(zip(entries, scores, strict=True), key=lambda p: p[1], reverse=True)
    return [(e, s) for e, s in ranked[:k] if s > 0]


def stale_entries(
    *,
    kb_dir: Path | None = None,
    staleness_days: int = DEFAULT_STALENESS_DAYS,
    now: datetime | None = None,
) -> list[KBEntry]:
    """Return paper/note entries whose ``last_checked`` is older than the window."""
    moment = now or _utcnow()
    cutoff = moment - timedelta(days=staleness_days)
    return [
        e
        for e in list_kb_entries(kb_dir)
        if e.kind in ("paper", "note") and e.last_checked < cutoff
    ]


def mark_checked(
    entry_id: str, *, kb_dir: Path | None = None, now: datetime | None = None
) -> KBEntry:
    """Record that an entry was re-checked (updates ``last_checked`` only).

    This never changes status or content — re-verification produces ordinary
    evidence in a workspace; here we only reset the staleness clock.
    """
    root = kb_root(kb_dir)
    entries = read_jsonl(_entries_path(root), KBEntry)
    updated: KBEntry | None = None
    for entry in entries:
        if entry.id == entry_id:
            entry.last_checked = now or _utcnow()
            updated = entry
    if updated is None:
        raise OpenTorusError(f"No KB entry with id '{entry_id}'.")
    rewrite_jsonl(_entries_path(root), entries)
    return updated
