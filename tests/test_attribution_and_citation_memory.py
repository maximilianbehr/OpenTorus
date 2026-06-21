"""Tests for B1 (no cross-dossier misattribution) and A7 (citation-failure memory)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.research.dossier import store
from opentorus.workspace import init_workspace, workspace_dir

runner = CliRunner()


# --- B1: bulk creation must not leave an arbitrary active problem -------------


def test_structured_bulk_creation_clears_active_problem(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    notes = tmp_path / "notes.md"
    notes.write_text(
        "# Problem: Least squares sketch-and-precondition\n\nBody one.\n\n"
        "# Problem: Nyström landmark sampling\n\nBody two.\n",
        encoding="utf-8",
    )
    res = runner.invoke(app, ["problem", "new", "--from-markdown", str(notes), "--structured"])
    assert res.exit_code == 0
    base = workspace_dir(tmp_path)
    assert len(store.list_dossiers(base)) == 2
    # No dossier is left arbitrarily active, so a later run/research cannot silently
    # attribute its artifacts to an unrelated problem.
    assert store.get_active_problem(base) is None


def test_single_structured_creation_keeps_active(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    notes = tmp_path / "one.md"
    notes.write_text("# Problem: Only one\n\nBody.\n", encoding="utf-8")
    runner.invoke(app, ["problem", "new", "--from-markdown", str(notes), "--structured"])
    base = workspace_dir(tmp_path)
    assert store.get_active_problem(base) == "PROBLEM-0001"  # unambiguous → stays active


def test_clear_active_problem(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    store.create_dossier(base, "A problem.")
    assert store.get_active_problem(base) == "PROBLEM-0001"
    store.clear_active_problem(base)
    assert store.get_active_problem(base) is None


# --- A7: citation failures persist and re-surface ----------------------------


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    return base, store.create_dossier(base, "Prove X.").id


def test_citation_failures_persist_and_merge(tmp_path: Path) -> None:
    from opentorus.research.paper_citations import known_bad_citations, record_citation_failures

    base, pid = _problem(tmp_path)
    errs = [
        "PAPER-0001 does not contain Theorem/Lemma 10.5 in parsed text — do not invent…",
        "PAPER-0001 is cited but has no parsed full text — call paper_fetch.",  # not recorded
    ]
    record_citation_failures(base, pid, errs)
    known = known_bad_citations(base, pid)
    assert any("Theorem/Lemma 10.5" in k for k in known)
    assert not any("no parsed full text" in k for k in known)  # only "does not contain" recorded
    # Recording again is idempotent (deduped).
    record_citation_failures(base, pid, errs)
    assert len(known_bad_citations(base, pid)) == len(known)


def test_proof_write_resurfaces_known_bad_citations(tmp_path: Path) -> None:
    from opentorus.research.papers import Paper, _save_meta, papers_dir
    from opentorus.tools.base import ToolCall
    from opentorus.tools.research import ProofWriteTool

    base, pid = _problem(tmp_path)
    # A parsed paper that does NOT contain the cited theorem.
    _save_meta(
        base,
        Paper(
            id="PAPER-0001",
            source="x",
            source_type="manual",
            structure_path="papers/PAPER-0001/structure.json",
        ),
    )
    s = papers_dir(base) / "PAPER-0001" / "structure.json"
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text('{"sections":[{"text":"Only Theorem 1 appears here."}]}', encoding="utf-8")

    tool = ProofWriteTool(base)
    args = {
        "problem_id": pid,
        "title": "Sketch citing a nonexistent theorem",
        "theorem": "X holds.",
        "main_proof": "By Theorem 9.9 of PAPER-0001 the bound holds, which proves the estimate.",
        "scope": "primary",
    }
    r = tool.run(ToolCall(id="1", name="proof_write", args=args))
    assert not r.ok
    assert "Known nonexistent citations" in r.content
    # The failure is persisted for re-feeding on later attempts / after compaction.
    from opentorus.research.paper_citations import known_bad_citations

    assert any("9.9" in k for k in known_bad_citations(base, pid))
