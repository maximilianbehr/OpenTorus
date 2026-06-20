"""Tests for beginner next-step suggestions."""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.suggest import suggest_next_commands
from opentorus.workspace import init_workspace, workspace_dir


def test_no_workspace_suggests_init() -> None:
    items = suggest_next_commands(None, None)
    assert items[0].command == "opentorus init"


def test_mock_provider_suggests_real_model(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    items = suggest_next_commands(tmp_path, ot, config)
    commands = {i.command for i in items}
    assert "opentorus config set model.provider ollama" in commands


def test_inbox_pdf_suggests_ingest(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    inbox = tmp_path / "papers" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "survey.pdf").write_bytes(b"%PDF")
    items = suggest_next_commands(tmp_path, ot, default_config())
    assert any("paper ingest" in i.command for i in items)


def test_pending_task_suggests_resume(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    from opentorus.research.tasks import create_task

    create_task(ot, "literature", "Read papers")
    items = suggest_next_commands(tmp_path, ot, default_config())
    assert any("run --plan --resume" in i.command for i in items)
