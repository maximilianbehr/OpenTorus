"""Tests for the eval harness (Milestone 36)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opentorus.errors import OpenTorusError
from opentorus.evals import get_suite, run_suite
from opentorus.evals.harness import EvalCase, _grade
from opentorus.workspace import init_workspace, workspace_dir


def test_smoke_suite_passes_deterministically(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    run = run_suite(ot, "smoke")
    assert run.total == 4
    assert run.all_passed, [r.detail for r in run.results if not r.passed]


def test_run_is_reproducible(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    first = run_suite(ot, "smoke")
    second = run_suite(ot, "smoke")
    assert first.passed == second.passed == first.total


def test_manifest_written(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    run = run_suite(ot, "smoke", seed=42)
    manifest = Path(run.manifest_path)
    assert manifest.is_file()
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert data["suite"] == "smoke"
    assert data["seed"] == 42
    assert data["environment"]["provider"] == "mock"
    assert "results" in data


def test_unknown_suite_raises(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    with pytest.raises(OpenTorusError):
        run_suite(ot, "does-not-exist")


def test_grader_detects_missing_keyword() -> None:
    case = EvalCase(name="x", goal="g", must_contain=["banana"], must_use_tool="status")
    result = _grade(case, "no fruit here", ["git_diff"])
    assert not result.passed
    assert "missing keywords: banana" in result.detail
    assert "expected tool 'status'" in result.detail


def test_grader_passes_when_satisfied() -> None:
    case = EvalCase(name="x", goal="g", must_contain=["found"], must_use_tool="status")
    result = _grade(case, "Here is what I FOUND", ["status"])
    assert result.passed


def test_get_suite_returns_cases() -> None:
    assert len(get_suite("smoke")) == 4
