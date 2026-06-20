"""Tests for quality gates (Milestone 14)."""

from __future__ import annotations

import sys
from pathlib import Path

from opentorus.actions import list_actions
from opentorus.config import default_config
from opentorus.quality import run_checks
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _with_python_project(root: Path) -> None:
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")


def test_run_checks_passing_gate_logs_action(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _with_python_project(tmp_path)
    config = default_config()
    config.quality.test_command = f"{sys.executable} -c \"print('ok')\""
    config.quality.lint_command = None
    config.quality.typecheck_command = None

    results = run_checks(tmp_path, ot, config)
    by_name = {r.name: r for r in results}
    assert by_name["test"].ok is True
    assert by_name["lint"].skipped is True
    assert by_name["typecheck"].skipped is True
    assert list_actions(ot)[-1].tool_name == "check"


def test_run_checks_failing_gate(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _with_python_project(tmp_path)
    config = default_config()
    config.quality.test_command = f'{sys.executable} -c "import sys; sys.exit(3)"'
    config.quality.lint_command = None
    config.quality.typecheck_command = None

    results = run_checks(tmp_path, ot, config)
    test_result = next(r for r in results if r.name == "test")
    assert test_result.ok is False
    assert test_result.exit_code == 3


def test_run_checks_only_filter(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _with_python_project(tmp_path)
    config = default_config()
    config.quality.test_command = f"{sys.executable} -c \"print('ok')\""
    results = run_checks(tmp_path, ot, config, only=["test"])
    assert [r.name for r in results] == ["test"]


def test_run_checks_skipped_without_python_project(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = default_config()
    results = run_checks(tmp_path, ot, config)
    assert all(r.skipped for r in results)
    assert all(r.ok for r in results)
    assert "no Python project" in (results[0].stdout_summary or "")
