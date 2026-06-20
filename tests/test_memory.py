"""Tests for JSONL persistence and structured memory (Milestone 3)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from opentorus.jsonl import append_jsonl, next_id, read_jsonl
from opentorus.research.memory import add_memory, list_memory
from opentorus.workspace import init_workspace, workspace_dir


class _Sample(BaseModel):
    id: str
    created_at: datetime


def test_append_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "data.jsonl"
    record = _Sample(id="X-0001", created_at=datetime(2026, 1, 1, tzinfo=UTC))
    append_jsonl(path, record)
    append_jsonl(path, record.model_copy(update={"id": "X-0002"}))

    records = read_jsonl(path, _Sample)
    assert [r.id for r in records] == ["X-0001", "X-0002"]


def test_datetime_serialized_as_iso_string(tmp_path: Path) -> None:
    path = tmp_path / "data.jsonl"
    append_jsonl(path, _Sample(id="X-0001", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
    raw = path.read_text(encoding="utf-8")
    assert "2026-01-01T00:00:00" in raw  # ISO, not a datetime repr


def test_corrupt_line_is_skipped_with_warning(tmp_path: Path, caplog) -> None:
    path = tmp_path / "data.jsonl"
    append_jsonl(path, _Sample(id="X-0001", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{ this is not valid json }\n")
    append_jsonl(path, _Sample(id="X-0002", created_at=datetime(2026, 1, 1, tzinfo=UTC)))

    with caplog.at_level("WARNING", logger="opentorus"):
        records = read_jsonl(path, _Sample)

    assert [r.id for r in records] == ["X-0001", "X-0002"]
    assert any("corrupt" in rec.message.lower() for rec in caplog.records)


def test_next_id_derives_from_max_suffix_not_count() -> None:
    # A count-based id collides when a line is corrupt and silently skipped;
    # next_id must derive from the highest existing suffix instead.
    assert next_id("CLAIM", []) == "CLAIM-0001"
    assert next_id("CLAIM", ["CLAIM-0001", "CLAIM-0002", "CLAIM-0003"]) == "CLAIM-0004"
    # Only two survive a corrupt middle line, but the max suffix is still 3.
    assert next_id("CLAIM", ["CLAIM-0001", "CLAIM-0003"]) == "CLAIM-0004"
    # Multi-segment prefixes (e.g. KB-PAPER) parse the trailing number.
    assert next_id("KB-PAPER", ["KB-PAPER-0007"]) == "KB-PAPER-0008"


def test_add_and_list_memory(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    e1 = add_memory(base, "facts", "JSONL is inspectable.")
    e2 = add_memory(base, "facts", "Memory lives in .opentorus/memory.")
    assert e1.id == "FACT-0001"
    assert e2.id == "FACT-0002"
    facts = list_memory(base, "facts")
    assert [f.text for f in facts] == [
        "JSONL is inspectable.",
        "Memory lives in .opentorus/memory.",
    ]


def test_memory_kinds_are_isolated(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    add_memory(base, "facts", "a fact")
    add_memory(base, "observations", "an observation")
    assert len(list_memory(base, "facts")) == 1
    assert len(list_memory(base, "observations")) == 1
