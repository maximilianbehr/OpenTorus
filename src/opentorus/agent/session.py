"""Session message schema and JSONL persistence.

Interactive turns are appended to ``.opentorus/session.jsonl`` so a session can
later be replayed and summarized.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.jsonl import append_jsonl, read_jsonl

Role = Literal["user", "assistant", "tool", "system"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SessionMessage(BaseModel):
    role: Role
    content: str
    # Base64-encoded PNG page images for vision models (Ollama ``images``, OpenAI/Anthropic blocks).
    images: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


def session_path(workspace_dir: Path) -> Path:
    return workspace_dir / "session.jsonl"


def append_message(workspace_dir: Path, message: SessionMessage) -> None:
    append_jsonl(session_path(workspace_dir), message)


def read_messages(workspace_dir: Path) -> list[SessionMessage]:
    return read_jsonl(session_path(workspace_dir), SessionMessage)
