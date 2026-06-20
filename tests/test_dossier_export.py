"""Tests for problem dossier export (Markdown + PDF)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.paths import WORKSPACE_DIRNAME
from opentorus.research.dossier import store
from opentorus.research.dossier.claims import add_proof_attempt
from opentorus.research.dossier.export import assemble_export_markdown, export_problem
from opentorus.workspace import init_workspace, workspace_dir

runner = CliRunner()


def test_assemble_export_includes_report_and_proofs(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Prove X.", title="Problem X")
    add_proof_attempt(
        ot,
        "PROBLEM-0001",
        title="Main sketch",
        body="# Theorem\n\nBy induction. [GAP-1] detail.",
        gaps=["Inductive step"],
    )
    text = assemble_export_markdown(ot, "PROBLEM-0001")
    assert "## Claims and Evidence" in text
    assert "PROOF-0001" in text
    assert "By induction" in text
    assert "## Proof Attempts" in text
    assert "Proof and Argument Appendices" not in text


def test_export_problem_writes_markdown(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Refute Y.", title="Problem Y")
    result = export_problem(ot, "PROBLEM-0001", pdf=False)
    assert result.markdown_path.is_file()
    assert result.pdf_path is None
    assert "Problem Y" in result.markdown_path.read_text()


def test_export_problem_pdf_calls_renderer(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Prove Z.", title="Problem Z")

    def fake_render(*args, **kwargs) -> None:
        kwargs["pdf_path"].write_bytes(b"%PDF-fake")

    # Patch tex_available too: on a runner without a LaTeX toolchain (e.g. CI),
    # export_problem would otherwise take the HTML-fallback path and never reach
    # the mocked renderer. Patching it keeps this test environment-independent.
    with (
        patch("opentorus.research.dossier.pdf_export.tex_available", return_value=True),
        patch(
            "opentorus.research.dossier.pdf_export.compose_and_render_pdf",
            side_effect=fake_render,
        ),
    ):
        result = export_problem(ot, "PROBLEM-0001", pdf=True, compose_llm=False)

    assert result.pdf_path is not None
    assert result.pdf_path.is_file()


def test_problem_export_cli(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    runner.invoke(app, ["problem", "new", "Conjecture: bound holds."])
    with (
        patch("opentorus.research.dossier.pdf_export.tex_available", return_value=True),
        patch(
            "opentorus.research.dossier.pdf_export.compose_and_render_pdf",
            side_effect=lambda *a, **kw: kw["pdf_path"].write_bytes(b"%PDF"),
        ),
    ):
        res = runner.invoke(app, ["problem", "export", "PROBLEM-0001", "--pdf"])
    assert res.exit_code == 0
    assert "Markdown" in res.stdout
    assert "PDF" in res.stdout
    md = tmp_path / WORKSPACE_DIRNAME / "problems" / "PROBLEM-0001" / "PROBLEM-0001-full.md"
    pdf = tmp_path / WORKSPACE_DIRNAME / "problems" / "PROBLEM-0001" / "PROBLEM-0001-full.pdf"
    assert md.is_file()
    assert pdf.is_file()


def test_export_missing_dossier(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    res = runner.invoke(app, ["problem", "export", "PROBLEM-0099"])
    assert res.exit_code != 0
