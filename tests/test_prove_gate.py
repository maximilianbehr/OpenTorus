"""Tests for prove-phase tool guards and paper_read."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.prove_gate import prove_tool_gate
from opentorus.research.papers import acquire_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.tools.base import ToolCall
from opentorus.tools.research import PaperReadTool
from opentorus.workspace import init_workspace, workspace_dir
from test_paper_extraction import FIXTURE_PAGES


def test_prove_gate_blocks_run_shell() -> None:
    gate = prove_tool_gate("PROBLEM-0002", deliverable_done=lambda: False)
    msg = gate("run_shell", {"command": "python scripts/counterexample_nystrom.py"})
    assert msg is not None
    assert "exp_new" in msg
    assert "exp_run" in msg


def test_prove_gate_blocks_opentorus_cli() -> None:
    gate = prove_tool_gate("PROBLEM-0002", deliverable_done=lambda: False)
    msg = gate("run_shell", {"command": "opentorus paper show PAPER-0001"})
    assert msg is not None
    assert "run_shell is not available" in msg


def test_prove_gate_blocks_pip_install() -> None:
    gate = prove_tool_gate("PROBLEM-0002", deliverable_done=lambda: False)
    msg = gate("run_shell", {"command": "python -m pip install --user numpy"})
    assert msg is not None
    assert "exp_new" in msg or "Docker" in msg


def test_report_build_no_longer_blocked(tmp_path: Path) -> None:
    gate = prove_tool_gate("PROBLEM-0002", deliverable_done=lambda: False)
    assert gate("report_build", {"title": "x"}) is None


def test_prove_gate_rejects_wrong_problem_id() -> None:
    # The model must not write the proof to a different dossier than the target.
    gate = prove_tool_gate("PROBLEM-0002", deliverable_done=lambda: False)
    msg = gate("proof_write", {"problem_id": "PROBLEM-0001", "title": "X", "theorem": "..."})
    assert msg is not None
    assert "PROBLEM-0002" in msg and "PROBLEM-0001" in msg


def test_prove_gate_allows_target_problem_id() -> None:
    gate = prove_tool_gate("PROBLEM-0002", deliverable_done=lambda: False)
    # Non-canonical form of the same id is accepted.
    assert gate("proof_write", {"problem_id": "problem-2", "title": "X"}) is None
    assert gate("claim_new", {"problem_id": "PROBLEM-0002", "statement": "..."}) is None


def test_prove_gate_ignores_calls_without_problem_id() -> None:
    gate = prove_tool_gate("PROBLEM-0002", deliverable_done=lambda: False)
    assert gate("read_file", {"path": "a.md"}) is None


def test_prove_gate_blocks_reading_another_dossier() -> None:
    # Single-problem session: the model must not wander to another PROBLEM-* via a path.
    gate = prove_tool_gate("PROBLEM-0003", deliverable_done=lambda: False)
    msg = gate("read_file", {"path": ".opentorus/problems/PROBLEM-0002/statement.md"})
    assert msg is not None
    assert "PROBLEM-0003" in msg and "PROBLEM-0002" in msg


def test_prove_gate_allows_own_dossier_and_other_paths() -> None:
    gate = prove_tool_gate("PROBLEM-0003", deliverable_done=lambda: False)
    assert gate("read_file", {"path": ".opentorus/problems/PROBLEM-0003/statement.md"}) is None
    assert gate("write_file", {"path": "scripts/run.py"}) is None
    assert gate("read_file", {"path": ".opentorus/papers/PAPER-0001/note.md"}) is None


def test_has_primary_proof_distinguishes_no_proof_from_zero_gap(tmp_path: Path) -> None:
    # "No proof for the target dossier" must not read as "deliverable complete".
    from opentorus.agent.prove_loop import has_primary_proof
    from opentorus.research.dossier import claims, store

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    d = store.create_dossier(ot, "Conjecture X.")
    assert has_primary_proof(ot, d.id) is False
    claims.add_proof_attempt(
        ot, d.id, title="sketch", body="step 1", kind="sketch", scope="primary"
    )
    assert has_primary_proof(ot, d.id) is True
    # An exploration-scope proof does not count as the dossier's primary deliverable.
    other = store.create_dossier(ot, "Conjecture Y.")
    claims.add_proof_attempt(
        ot, other.id, title="aside", body="...", kind="sketch", scope="exploration"
    )
    assert has_primary_proof(ot, other.id) is False


def test_paper_read_returns_note(tmp_path: Path, monkeypatch) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    record = SourceRecord(source="arxiv", title="Sign bounds", arxiv_id="2401.77777")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")

    import opentorus.research.papers as papers_mod

    original_read = papers_mod.read_paper

    def _read(ot_dir, paper_id, page_extractor=None):
        return original_read(ot_dir, paper_id, page_extractor=lambda _p: FIXTURE_PAGES)

    monkeypatch.setattr(papers_mod, "read_paper", _read)
    papers_mod.read_paper(ot, paper.id)

    result = PaperReadTool(ot).run(ToolCall(name="paper_read", args={"paper_id": paper.id}))
    assert result.ok is True
    assert "Reading note" in result.content
    assert "preconditioner" in result.content
