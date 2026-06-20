"""Tests for the active/current PROBLEM pointer (A: ergonomic multi-problem)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.cli._base import _resolve_problem_id
from opentorus.errors import OpenTorusError
from opentorus.research.dossier import store
from opentorus.workspace import init_workspace, workspace_dir

runner = CliRunner()


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_create_dossier_sets_active(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    a = store.create_dossier(base, "First about X.")
    assert store.get_active_problem(base) == a.id
    b = store.create_dossier(base, "Second about Y.")
    assert store.get_active_problem(base) == b.id  # newest becomes active


def test_set_and_get_active(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    a = store.create_dossier(base, "First.")
    store.create_dossier(base, "Second.")
    store.set_active_problem(base, a.id)
    assert store.get_active_problem(base) == a.id


def test_get_active_none_when_unset(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    assert store.get_active_problem(base) is None


def test_resolve_explicit_is_canonicalized(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    store.create_dossier(base, "First.")
    store.create_dossier(base, "Second.")
    assert _resolve_problem_id(base, "problem-2") == "PROBLEM-0002"
    assert _resolve_problem_id(base, "PROBLEM-0001") == "PROBLEM-0001"


def test_resolve_falls_back_to_active(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    a = store.create_dossier(base, "First.")
    assert _resolve_problem_id(base, None) == a.id


def test_resolve_errors_without_active_or_id(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    try:
        _resolve_problem_id(base, None)
    except OpenTorusError as exc:
        assert "no active problem" in str(exc).lower()
    else:
        raise AssertionError("expected OpenTorusError when neither id nor active problem")


def test_cli_use_then_omit_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    runner.invoke(app, ["problem", "new", "First problem."])
    runner.invoke(app, ["problem", "new", "Second problem."])
    # Select the first as active, then `show` with no id must target it.
    assert runner.invoke(app, ["problem", "use", "PROBLEM-0001"]).exit_code == 0
    res = runner.invoke(app, ["problem", "show"])
    assert res.exit_code == 0
    assert "PROBLEM-0001" in res.stdout
    assert "First problem" in res.stdout


def test_cli_show_without_active_errors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    res = runner.invoke(app, ["problem", "show"])
    assert res.exit_code != 0
