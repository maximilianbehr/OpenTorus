"""Smoke tests for the CLI plus workspace init/status (Milestone 1)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import opentorus
from opentorus.cli import app
from opentorus.paths import WORKSPACE_DIRNAME
from opentorus.workspace import init_workspace

runner = CliRunner()


def test_version_is_non_empty_string() -> None:
    assert isinstance(opentorus.__version__, str)
    assert opentorus.__version__


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_help_commands_are_alphabetically_sorted() -> None:
    from typer.main import get_command

    command = get_command(app)
    ctx = command.make_context("opentorus", [], resilient_parsing=True)
    names = command.list_commands(ctx)
    assert names == sorted(names)


def test_init_creates_structure(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    base = tmp_path / WORKSPACE_DIRNAME
    assert (base / "config.yaml").is_file()
    assert (base / "permissions.yaml").is_file()
    for name in ("session.jsonl", "actions.jsonl", "graph.jsonl", "evidence.jsonl"):
        assert (base / name).is_file()
    assert (base / "memory" / "claims.jsonl").is_file()
    for dirname in ("experiments", "papers", "summaries", "tasks", "patches"):
        assert (base / dirname).is_dir()


def test_init_is_idempotent_and_preserves_data(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    claims = tmp_path / WORKSPACE_DIRNAME / "memory" / "claims.jsonl"
    claims.write_text('{"id": "CLAIM-0001"}\n', encoding="utf-8")

    created_again = init_workspace(tmp_path)

    assert created_again == []  # nothing new created
    assert claims.read_text(encoding="utf-8") == '{"id": "CLAIM-0001"}\n'


def test_init_command_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / WORKSPACE_DIRNAME).is_dir()


def test_paper_ingest_requires_local_workspace(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    init_workspace(parent)
    project = tmp_path / "simon_workshop"
    project.mkdir()
    (project / "papers").mkdir()
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["paper", "ingest"])
    assert result.exit_code == 1
    assert "opentorus init" in result.stdout
    assert "papers" in result.stdout


def test_status_command_without_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Initialized" in result.stdout
