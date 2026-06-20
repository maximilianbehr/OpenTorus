"""Tests for scoped quality gates after edits."""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.quality import run_checks
from opentorus.workspace import init_workspace, workspace_dir


def test_run_checks_skips_test_and_lint_for_markdown_only_edit(tmp_path: Path) -> None:
    root = tmp_path
    init_workspace(root)
    ot_dir = workspace_dir(root)
    (root / "scripts").mkdir()
    (root / "scripts" / "bad.py").write_text("import os\nx = 1\n", encoding="utf-8")
    (root / "reports").mkdir()
    config = default_config()

    checks = run_checks(root, ot_dir, config, edited_paths=["reports/note.md"])

    by_name = {c.name: c for c in checks}
    assert by_name["test"].skipped
    assert by_name["lint"].skipped
    assert by_name["typecheck"].skipped


def test_run_checks_skips_test_when_no_tests_directory(tmp_path: Path) -> None:
    root = tmp_path
    init_workspace(root)
    ot_dir = workspace_dir(root)
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    config = default_config()

    checks = run_checks(root, ot_dir, config)

    by_name = {c.name: c for c in checks}
    assert by_name["test"].skipped
    assert "no tests" in (by_name["test"].stdout_summary or "")
    assert by_name["lint"].command == "ruff check ."
