"""Tests for the typecheck quality gate (Milestone 38)."""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.quality import run_checks
from opentorus.workspace import init_workspace, workspace_dir


def test_typecheck_is_a_default_gate() -> None:
    config = default_config()
    assert config.quality.typecheck_command == "mypy"
    assert config.quality.lint_command == "ruff check ."


def test_run_checks_includes_typecheck(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    ot = workspace_dir(tmp_path)
    config = default_config()
    # Use trivial commands so the test does not depend on mypy/ruff being present.
    config.quality.test_command = "true"
    config.quality.lint_command = "true"
    config.quality.typecheck_command = "true"
    results = run_checks(tmp_path, ot, config)
    names = {r.name for r in results}
    assert "typecheck" in names
    typecheck = next(r for r in results if r.name == "typecheck")
    assert typecheck.ok
    assert not typecheck.skipped


def test_typecheck_failure_is_reported(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.quality.test_command = "true"
    config.quality.lint_command = "true"
    config.quality.typecheck_command = "false"
    results = run_checks(tmp_path, ot, config, only=["typecheck"])
    assert len(results) == 1
    assert not results[0].ok
