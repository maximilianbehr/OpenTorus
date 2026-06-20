"""Tests for the reviewer artifact pack (Milestone 69)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from opentorus.research.experiments import new_experiment, run_experiment
from opentorus.research.figures import new_figure, stdlib_svg_script
from opentorus.research.pack import (
    export_experiment_notebook,
    export_pack,
    read_pack_manifest,
    reproduce_pack,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_pack_round_trips_artifacts(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    figure = new_figure(
        ot, "fig", plot_script=stdlib_svg_script([1.0, 2.0]), caption="Evidence only."
    )

    pack_path = export_pack(ot)
    with zipfile.ZipFile(pack_path) as zf:
        names = zf.namelist()
    assert any(n.startswith("pack/figures/") and n.endswith(".svg") for n in names)
    manifest = read_pack_manifest(pack_path)
    assert manifest.experiment_count == 0
    _ = figure


def test_pack_excludes_pdfs(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    papers = ot / "papers" / "PAPER-0001"
    papers.mkdir(parents=True, exist_ok=True)
    (papers / "fulltext.pdf").write_bytes(b"%PDF-1.4 fake")
    (papers / "note.md").write_text("notes", encoding="utf-8")
    pack_path = export_pack(ot)
    with zipfile.ZipFile(pack_path) as zf:
        names = zf.namelist()
    assert not any(n.endswith(".pdf") for n in names)
    assert any(n.endswith("note.md") for n in names)


def test_reproduce_flags_injected_mismatch(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "repro", template="counterexample_search")
    run_experiment(ot, exp.id, timeout=30)
    stdout = ot / exp.path / "results" / "stdout.txt"
    stdout.write_text('{"seed": 0, "tampered": true}\n', encoding="utf-8")
    reports = reproduce_pack(ot)
    assert reports
    assert reports[0].reproducible is False


def test_reproduce_clean_run_is_reproducible(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "clean", template="counterexample_search")
    run_experiment(ot, exp.id, timeout=30)
    reports = reproduce_pack(ot)
    assert reports
    assert reports[0].reproducible is True


def test_notebook_export_is_valid(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "nb", template="counterexample_search")
    run_experiment(ot, exp.id, timeout=30)
    nb_path = export_experiment_notebook(ot, exp.id)
    data = json.loads(nb_path.read_text())
    assert data["nbformat"] == 4
    assert any(c["cell_type"] == "code" for c in data["cells"])
    assert all("source" in c for c in data["cells"])
