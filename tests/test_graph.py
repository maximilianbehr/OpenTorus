"""Tests for the artifact graph (Milestone 16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.graph import (
    add_edge,
    export_graph,
    list_edges,
    related,
    to_ascii,
    to_mermaid,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_add_and_list_edges(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    edge = add_edge(ot, "EXP-0001", "CLAIM-0001", "tests", "exp checks the claim")
    assert edge.id == "EDGE-0001"
    assert edge.relation == "tests"
    edges = list_edges(ot)
    assert len(edges) == 1
    assert edges[0].rationale == "exp checks the claim"


def test_invalid_relation_rejected(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        add_edge(ot, "EXP-0001", "CLAIM-0001", "proves")


def test_related_finds_both_directions(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    add_edge(ot, "EXP-0001", "CLAIM-0001", "tests")
    add_edge(ot, "PAPER-0001", "CLAIM-0001", "cites")
    add_edge(ot, "EXP-0002", "PAPER-0001", "derived_from")

    claim_edges = related(ot, "CLAIM-0001")
    assert len(claim_edges) == 2
    assert {e.relation for e in claim_edges} == {"tests", "cites"}

    exp_edges = related(ot, "EXP-0001")
    assert len(exp_edges) == 1


def test_sequential_edge_ids(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    a = add_edge(ot, "A", "B", "supports")
    b = add_edge(ot, "B", "C", "blocks")
    assert (a.id, b.id) == ("EDGE-0001", "EDGE-0002")


def test_export_mermaid(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    add_edge(ot, "EXP-0001", "CLAIM-0001", "tests")
    add_edge(ot, "EXP-0002", "CLAIM-0001", "contradicts")
    diagram = export_graph(ot, "mermaid")
    assert diagram.startswith("graph LR")
    # Node ids are sanitized; the labels keep the original artifact ids.
    assert 'EXP_0001["EXP-0001"]' in diagram
    assert "|tests|" in diagram
    # Opposing relations use the thick link style.
    assert "==>|contradicts|" in diagram


def test_export_ascii(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    add_edge(ot, "EXP-0001", "CLAIM-0001", "tests")
    text = export_graph(ot, "ascii")
    assert "EXP-0001 --tests--> CLAIM-0001" in text


def test_export_empty_graph() -> None:
    assert to_ascii([]) == "(empty graph)"
    assert to_mermaid([]) == "graph LR"


def test_export_unknown_format(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        export_graph(ot, "dot")


def test_export_open_writes_html(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    add_edge(ot, "EXP-0001", "CLAIM-0001", "tests")
    rendered = export_graph(ot, "mermaid", open_file=True)
    html = ot / "graph.html"
    assert html.is_file()
    content = html.read_text(encoding="utf-8")
    assert "mermaid" in content
    assert "graph LR" in content
    assert str(html) in rendered
