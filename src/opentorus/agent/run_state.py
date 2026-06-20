"""Persist the last agent run so ``opentorus run --resume`` can continue."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

RunMode = Literal["run", "plan"]


class RunState(BaseModel):
    goal: str
    session_id: str
    mode: RunMode = "run"
    batch_task_ids: list[str] = []


def run_state_path(ot_dir: Path) -> Path:
    return ot_dir / "run_state.json"


def load_run_state(ot_dir: Path) -> RunState | None:
    path = run_state_path(ot_dir)
    if not path.is_file():
        return None
    return RunState.model_validate_json(path.read_text(encoding="utf-8"))


def save_run_state(ot_dir: Path, state: RunState) -> None:
    run_state_path(ot_dir).write_text(state.model_dump_json(indent=2), encoding="utf-8")
