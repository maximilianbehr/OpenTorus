"""Action log: every tool action is recorded for auditability and replay.

Entries are appended to ``.opentorus/actions.jsonl``. The schema is designed so
future deterministic replay is possible, even though MVP only needs a readable
history.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ActionLogEntry(BaseModel):
    id: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    permission_decision: dict = Field(default_factory=dict)
    ok: bool
    stdout_summary: str | None = None
    stderr_summary: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


def actions_path(workspace_dir: Path) -> Path:
    return workspace_dir / "actions.jsonl"


def log_action(
    workspace_dir: Path,
    tool_name: str,
    *,
    ok: bool,
    args: dict | None = None,
    permission_decision: dict | None = None,
    stdout_summary: str | None = None,
    stderr_summary: str | None = None,
    changed_files: list[str] | None = None,
) -> ActionLogEntry:
    path = actions_path(workspace_dir)
    existing = read_jsonl(path, ActionLogEntry)
    entry = ActionLogEntry(
        id=next_sequential_id("ACTION", len(existing)),
        tool_name=tool_name,
        args=args or {},
        permission_decision=permission_decision or {},
        ok=ok,
        stdout_summary=stdout_summary,
        stderr_summary=stderr_summary,
        changed_files=changed_files or [],
    )
    append_jsonl(path, entry)
    return entry


def list_actions(workspace_dir: Path, limit: int | None = None) -> list[ActionLogEntry]:
    entries = read_jsonl(actions_path(workspace_dir), ActionLogEntry)
    if limit is not None:
        return entries[-limit:]
    return entries
