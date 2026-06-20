"""Tests for the new REPL slash commands: /why, /report, /problem."""

from __future__ import annotations

from pathlib import Path

from opentorus.repl import dispatch
from opentorus.research.dossier import claims, store
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_help_lists_new_commands() -> None:
    out = dispatch("/help").messages[0]
    assert "/why" in out and "/report" in out and "/problem" in out


def test_problem_command_lists_and_marks_active(tmp_path: Path, monkeypatch) -> None:
    base = _ws(tmp_path, monkeypatch)
    store.create_dossier(base, "First problem.")
    store.create_dossier(base, "Second problem.")
    out = dispatch("/problem").messages[0]
    assert "PROBLEM-0001" in out and "PROBLEM-0002" in out
    assert "→ PROBLEM-0002" in out  # newest is active


def test_problem_command_sets_active(tmp_path: Path, monkeypatch) -> None:
    base = _ws(tmp_path, monkeypatch)
    store.create_dossier(base, "First.")
    store.create_dossier(base, "Second.")
    msg = dispatch("/problem PROBLEM-0001").messages[0]
    assert "Active problem set to PROBLEM-0001" in msg
    assert store.get_active_problem(base) == "PROBLEM-0001"


def test_why_traces_claim_evidence(tmp_path: Path, monkeypatch) -> None:
    base = _ws(tmp_path, monkeypatch)
    d = store.create_dossier(base, "Conjecture X.")
    c = claims.add_claim(base, d.id, claim_type="CONJECTURE", statement="X holds.")
    claims.add_evidence(base, d.id, c.id, evidence_type="EXPERIMENT", summary="held")
    out = dispatch(f"/why {c.id}").messages[0]
    assert c.id in out
    assert "supporting" in out


def test_why_without_id_shows_usage(tmp_path: Path, monkeypatch) -> None:
    _ws(tmp_path, monkeypatch)
    assert "Usage" in dispatch("/why").messages[0]


def test_report_builds_for_active(tmp_path: Path, monkeypatch) -> None:
    base = _ws(tmp_path, monkeypatch)
    d = store.create_dossier(base, "Conjecture X.")
    claims.add_claim(base, d.id, claim_type="CONJECTURE", statement="X holds.")
    msg = dispatch("/report").messages[0]
    assert d.id in msg
    assert (store.dossier_dir(base, d.id) / "report.md").is_file()


def test_report_without_problem(tmp_path: Path, monkeypatch) -> None:
    _ws(tmp_path, monkeypatch)
    assert "no active problem" in dispatch("/report").messages[0].lower()
