"""Tests for figure & plot artifacts (Milestone 67).

A figure records its script + data hash + caption and a graph edge to its source;
regeneration is deterministic. Offline, headless (stdlib SVG, no matplotlib).
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.figures import (
    get_figure,
    new_figure,
    regenerate_figure,
    stdlib_svg_script,
)
from opentorus.research.graph import related
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _claim(ot: Path, statement: str):
    from opentorus.research.claims import new_claim

    return new_claim(ot, statement)


def _experiment(ot: Path):
    from opentorus.research.experiments import new_experiment, run_experiment

    exp = new_experiment(ot, "src", template="counterexample_search")
    run_experiment(ot, exp.id, timeout=30)
    return exp


def test_figure_records_script_data_hash_caption(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    script = stdlib_svg_script([1.0, 2.0, 3.0], title="bars")
    figure = new_figure(
        ot,
        "Bar chart",
        plot_script=script,
        caption="Counts per bucket (evidence, not a verified distribution).",
        data="1,2,3",
    )
    assert figure.exit_code == 0
    assert figure.script_path.endswith("plot.py")
    assert figure.image_path and figure.image_path.endswith(".svg")
    assert figure.data_hash  # non-empty hash of the input data
    assert (ot / figure.image_path).is_file()
    assert "evidence" in figure.caption


def test_figure_links_to_experiment_and_claim(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "The distribution is bimodal.")
    exp = _experiment(ot)
    figure = new_figure(
        ot,
        "Linked figure",
        plot_script=stdlib_svg_script([5.0, 1.0, 5.0]),
        caption="Two modes shown (bounded evidence).",
        experiment_id=exp.id,
        claim_id=claim.id,
    )
    edges = related(ot, figure.id)
    assert any(e.relation == "generated_by" and e.target_id == exp.id for e in edges)
    assert any(e.relation == "explains" and e.target_id == claim.id for e in edges)


def test_regeneration_is_deterministic(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    figure = new_figure(
        ot,
        "Deterministic",
        plot_script=stdlib_svg_script([1.0, 4.0, 9.0]),
        caption="Squares (evidence).",
    )
    assert figure.output_hash
    deterministic, new_hash = regenerate_figure(ot, figure.id)
    assert deterministic is True
    assert new_hash == figure.output_hash


def test_figure_persisted_and_retrievable(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    figure = new_figure(
        ot, "Persisted", plot_script=stdlib_svg_script([2.0]), caption="One bar (evidence)."
    )
    assert get_figure(ot, figure.id) is not None
    assert figure.backend == "local"
