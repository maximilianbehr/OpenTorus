"""Tests for deterministic 1:1 structured problem extraction (B)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.research.dossier import store
from opentorus.research.problem_extraction import split_markdown_problems
from opentorus.workspace import workspace_dir

runner = CliRunner()

_NOTES = """\
# Problem: Foldability of widgets

Prove or refute: every widget folds.

## Sub-detail

Some context here.

# Problem: Color of gadgets

Determine the chromatic number of every gadget.
"""


def test_split_markdown_problems_one_to_one() -> None:
    sections = split_markdown_problems(_NOTES)
    assert len(sections) == 2  # two top-level (#) headings; ## is nested, not split
    titles = [t for t, _ in sections]
    assert titles == ["Problem: Foldability of widgets", "Problem: Color of gadgets"]
    # The statement carries the title and the section body (including sub-headings).
    assert "every widget folds" in sections[0][1]
    assert "Sub-detail" in sections[0][1]
    assert "chromatic number" in sections[1][1]


def test_split_markdown_problems_no_headings() -> None:
    assert split_markdown_problems("just prose, no headings") == []


def test_cli_structured_creates_one_dossier_per_heading(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    notes = tmp_path / "notes.md"
    notes.write_text(_NOTES, encoding="utf-8")
    res = runner.invoke(app, ["problem", "new", "--from-markdown", str(notes), "--structured"])
    assert res.exit_code == 0, res.stdout
    base = workspace_dir(tmp_path)
    dossiers = store.list_dossiers(base)
    assert len(dossiers) == 2
    assert "PROBLEM-0001" in res.stdout and "PROBLEM-0002" in res.stdout
    # Deterministic: statements match the headings, no model involved.
    # Bulk creation leaves NO arbitrary active problem (so a later run/research cannot
    # silently mis-attribute its artifacts to whichever was created last).
    assert store.get_active_problem(base) is None
