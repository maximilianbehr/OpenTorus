"""Tests for provenance drill-down and the read-only dashboard (Milestone 74)."""

from __future__ import annotations

from opentorus.research.claims import new_claim, update_claim
from opentorus.research.evidence import add_evidence
from opentorus.research.experiments import new_experiment
from opentorus.research.explain import (
    artifact_kind,
    build_dashboard_html,
    explain,
    export_dashboard,
    render_explain_text,
)
from opentorus.research.graph import add_edge, list_edges


def _ot(tmp_path):  # noqa: ANN001
    ot = tmp_path / ".opentorus"
    ot.mkdir()
    return ot


def test_artifact_kind_detection() -> None:
    assert artifact_kind("CLAIM-0001") == "claim"
    assert artifact_kind("PAPER-0007") == "paper"
    assert artifact_kind("DATASET-0001") == "dataset"
    assert artifact_kind("WHATEVER-1") == "artifact"


def test_explain_returns_provenance_subgraph_with_contradiction(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    claim = new_claim(ot, "The bound is tight.")
    update_claim(ot, claim.id, status="numerical_evidence")

    # A cited experiment must exist as a real artifact (integrity gate).
    new_experiment(ot, "bounded search")
    add_evidence(
        ot,
        claim.id,
        source_type="experiment",
        source_id="EXP-0001",
        summary="bounded search clean",
        direction="supports",
        strength="moderate",
    )
    add_evidence(
        ot,
        claim.id,
        source_type="paper",
        source_id="PAPER-0002",
        summary="counterexample reported",
        direction="contradicts",
        strength="strong",
    )
    add_edge(ot, "EXP-0001", claim.id, "supports", rationale="search")
    add_edge(ot, "PAPER-0002", claim.id, "contradicts", rationale="counterexample")
    # An unrelated edge must not appear in the subgraph.
    add_edge(ot, "PAPER-9999", "PAPER-0001", "cites")

    result = explain(ot, claim.id)
    assert result.kind == "claim"
    assert result.status == "numerical_evidence"
    assert "numerical evidence" in result.rigor
    assert [e.source_id for e in result.supporting] == ["EXP-0001"]
    assert [e.source_id for e in result.contradicting] == ["PAPER-0002"]
    # Subgraph is exactly the edges touching the claim, deterministically ordered.
    ids = [(e.source_id, e.target_id) for e in result.edges]
    assert ids == [("EXP-0001", claim.id), ("PAPER-0002", claim.id)]
    assert set(result.neighbors) == {"EXP-0001", "PAPER-0002"}


def test_explain_is_read_only_and_deterministic(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    claim = new_claim(ot, "Reproducible claim.")
    add_edge(ot, "EXP-0001", claim.id, "tests")

    edges_before = len(list_edges(ot))
    first = explain(ot, claim.id)
    second = explain(ot, claim.id)
    # No mutation, identical output.
    assert len(list_edges(ot)) == edges_before
    assert first.model_dump_json() == second.model_dump_json()
    # Renders without error and mentions the claim.
    text = render_explain_text(first)
    assert claim.id in text


def test_explain_lists_open_blocking_findings(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    from opentorus.agent.review import review_target

    claim = new_claim(ot, "We have proven the main theorem. QED.")
    review_target(ot, claim.id)
    result = explain(ot, claim.id)
    assert result.open_findings


def test_dashboard_export_is_deterministic_and_readonly(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    claim = new_claim(ot, "Dashboard claim.")
    update_claim(ot, claim.id, status="conjecture")
    add_edge(ot, "EXP-0001", claim.id, "tests")

    html1 = build_dashboard_html(ot)
    html2 = build_dashboard_html(ot)
    assert html1 == html2  # deterministic (no embedded timestamps)
    assert "read-only" in html1.lower()
    assert claim.id in html1
    assert "conjecture" in html1

    out = export_dashboard(ot)
    assert out.is_file()
    assert out.read_text(encoding="utf-8") == html1
