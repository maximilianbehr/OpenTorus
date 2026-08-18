"""Renderers (plain / JSON / DOT), the pure filter/search helpers, and the
``campaign tree`` command through the CliRunner on a mock campaign."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opentorus.campaign.models import RootRelation
from opentorus.campaign.proof_tree.models import (
    ROOT_ID,
    ProofEdge,
    ProofGraph,
    ProofNode,
    ProofNodeKind,
)
from opentorus.campaign.proof_tree.render import (
    LEGEND,
    STATUS_NOTE,
    SYMBOL_BAD,
    SYMBOL_FLAG,
    SYMBOL_OK,
    SYMBOL_OPEN,
    SYMBOL_SPECIAL,
    SYMBOL_UNKNOWN,
    filter_graph,
    render_dot,
    render_json,
    render_plain,
    search_nodes,
    symbol_for,
    tree_rows,
)
from opentorus.cli import app
from opentorus.paths import WORKSPACE_DIRNAME

runner = CliRunner()


def _fixture_graph() -> ProofGraph:
    """A small hand-built graph exercising every symbol and several relations."""
    nodes = [
        ProofNode(
            node_id=ROOT_ID,
            kind=ProofNodeKind.root,
            title="For every n, P(n)",
            status="UNSOLVED",
            root_relation=RootRelation.equivalent,
        ),
        ProofNode(
            node_id="BRANCH-0001",
            kind=ProofNodeKind.branch,
            title="Proof by induction",
            status="active",
            root_relation=RootRelation.equivalent,
            parents=[ROOT_ID],
            extra={"kind": "proof", "actual_cost": {"steps": 3}},
        ),
        ProofNode(
            node_id="BRANCH-0002",
            kind=ProofNodeKind.branch,
            title="Small n",
            status="suspended",
            root_relation=RootRelation.special_case,
            parents=[ROOT_ID],
            extra={"kind": "special-case", "suspension_reason": "BRANCH_EXHAUSTED"},
        ),
        ProofNode(
            node_id="OBL-0001",
            kind=ProofNodeKind.obligation,
            title="Induction step",
            status="open",
            root_relation=RootRelation.equivalent,
            parents=["BRANCH-0001"],
            extra={"closure_modes": ["formal_proof"]},
        ),
        ProofNode(
            node_id="OBL-0002",
            kind=ProofNodeKind.obligation,
            title="n <= 5",
            status="closed",
            root_relation=RootRelation.special_case,
            parents=["BRANCH-0002"],
            extra={
                "closed_by_artifact": "PROOF-0001",
                "closed_by_mode": "exact_symbolic_certificate",
                "closure_modes": ["exact_symbolic_certificate"],
            },
        ),
        ProofNode(
            node_id="PROOF-0001@verifier",
            kind=ProofNodeKind.verification,
            title="sympy accepted",
            status="accepted",
            parents=["OBL-0002"],
            extra={"artifact_id": "PROOF-0001", "backend": "sympy"},
        ),
        ProofNode(
            node_id="CLAIM-0001",
            kind=ProofNodeKind.claim,
            title="CONJECTURE CLAIM-0001",
            statement="P(n) for all n",
            status="unverified",
            root_relation=RootRelation.equivalent,
            parents=[ROOT_ID],
        ),
        ProofNode(
            node_id="EVID-0001",
            kind=ProofNodeKind.evidence,
            title="EXPERIMENT evidence",
            statement="holds up to 10^6",
            status="supports",
            parents=["CLAIM-0001"],
            extra={"evidence_type": "EXPERIMENT"},
        ),
        ProofNode(
            node_id="CLAIM-0002",
            kind=ProofNodeKind.counterexample,
            title="COUNTEREXAMPLE_CANDIDATE",
            status="contradicted",
            root_relation=RootRelation.counterexample_route,
            parents=[ROOT_ID],
        ),
        ProofNode(
            node_id="FSIG-0001",
            kind=ProofNodeKind.failed_attempt,
            title="formalization: tool_unavailable",
            status="tool_unavailable",
            parents=["BRANCH-0001"],
            extra={"occurrences": 2},
        ),
    ]
    edges = [
        ProofEdge(source_id="BRANCH-0001", target_id=ROOT_ID, relation="parent"),
        ProofEdge(source_id="BRANCH-0002", target_id=ROOT_ID, relation="parent"),
        ProofEdge(source_id="BRANCH-0002", target_id=ROOT_ID, relation="specializes"),
        ProofEdge(source_id="OBL-0001", target_id="BRANCH-0001", relation="parent"),
        ProofEdge(source_id="OBL-0002", target_id="BRANCH-0002", relation="parent"),
        ProofEdge(source_id="PROOF-0001@verifier", target_id="OBL-0002", relation="parent"),
        ProofEdge(source_id="PROOF-0001@verifier", target_id="OBL-0002", relation="closes"),
        ProofEdge(source_id="CLAIM-0001", target_id=ROOT_ID, relation="parent"),
        ProofEdge(source_id="EVID-0001", target_id="CLAIM-0001", relation="parent"),
        ProofEdge(source_id="EVID-0001", target_id="CLAIM-0001", relation="supports"),
        ProofEdge(source_id="CLAIM-0002", target_id=ROOT_ID, relation="parent"),
        ProofEdge(source_id="FSIG-0001", target_id="BRANCH-0001", relation="parent"),
    ]
    graph = ProofGraph(
        problem_id="PROBLEM-0001",
        campaign_id="CAMPAIGN-0001",
        nodes={n.node_id: n for n in nodes},
        edges=edges,
    )
    graph.root_status.report_status = "UNSOLVED"
    graph.root_status.label = "INCONCLUSIVE"
    graph.root_status.rationale = "no verification-grade artifact"
    return graph


# --------------------------------------------------------------------------------------
# symbols, plain
# --------------------------------------------------------------------------------------


def test_symbols_cover_every_family() -> None:
    g = _fixture_graph()
    assert symbol_for(g.nodes["OBL-0001"]) == SYMBOL_OPEN
    assert symbol_for(g.nodes["OBL-0002"]) == SYMBOL_OK + SYMBOL_SPECIAL
    assert symbol_for(g.nodes["BRANCH-0002"]) == SYMBOL_FLAG + SYMBOL_SPECIAL
    assert symbol_for(g.nodes["CLAIM-0002"]) == SYMBOL_BAD
    assert symbol_for(g.nodes["FSIG-0001"]) == SYMBOL_BAD  # a failure, whatever its category
    assert symbol_for(g.nodes["PROOF-0001@verifier"]) == SYMBOL_OK
    odd = ProofNode(node_id="X", kind=ProofNodeKind.claim, status="something-new")
    assert symbol_for(odd) == SYMBOL_UNKNOWN


def test_plain_contains_status_note_legend_relations_and_details() -> None:
    text = render_plain(_fixture_graph())
    assert text.startswith("Proof tree: PROBLEM-0001 (campaign CAMPAIGN-0001)\n")
    assert "Problem status (derived from dossier artifacts): UNSOLVED / INCONCLUSIVE" in text
    assert STATUS_NOTE in text and LEGEND in text
    for rel in ("[equivalent]", "[special-case]", "[counterexample-route]", "[unknown]"):
        assert rel in text
    assert "closed by PROOF-0001 (exact_symbolic_certificate)" in text
    assert "closable by formal_proof" in text
    assert "kind=proof steps=3" in text and "suspended=BRANCH_EXHAUSTED" in text
    assert "type=EXPERIMENT" in text
    assert "Issues: none" in text
    # nesting: OBL-0001 is indented under BRANCH-0001 which is under ROOT
    lines = text.splitlines()
    root_line = next(i for i, ln in enumerate(lines) if ln.startswith(f"{SYMBOL_OPEN} ROOT"))
    branch_line = next(i for i, ln in enumerate(lines) if "BRANCH-0001 [" in ln)
    ob_line = next(i for i, ln in enumerate(lines) if "OBL-0001 [" in ln)
    assert root_line < branch_line < ob_line
    assert lines[branch_line].startswith("  ") and lines[ob_line].startswith("    ")
    assert "Unattached" not in text


def test_plain_without_symbols_and_with_issues() -> None:
    graph = _fixture_graph()
    graph.nodes["GHOST-CHILD"] = ProofNode(
        node_id="GHOST-CHILD", kind=ProofNodeKind.claim, status="unverified", parents=["NOPE"]
    )
    from opentorus.campaign.proof_tree.validation import validate_graph

    graph.issues.extend(validate_graph(graph))
    text = render_plain(graph, show_symbols=False)
    assert LEGEND not in text
    assert SYMBOL_OPEN + " ROOT" not in text and "ROOT [equivalent] root" in text
    assert "Issues (" in text and "[error] missing_ref" in text
    assert "Unattached (no parent path to the root):" in text and "GHOST-CHILD" in text


def test_tree_rows_are_cycle_safe_and_mark_repeats() -> None:
    a = ProofNode(node_id="A", kind=ProofNodeKind.claim, status="unverified", parents=["B"])
    b = ProofNode(node_id="B", kind=ProofNodeKind.claim, status="unverified", parents=["A"])
    root = ProofNode(node_id=ROOT_ID, kind=ProofNodeKind.root, status="UNSOLVED")
    graph = ProofGraph(
        problem_id="P",
        nodes={ROOT_ID: root, "A": a, "B": b},
        edges=[
            ProofEdge(source_id="A", target_id="B", relation="parent"),
            ProofEdge(source_id="B", target_id="A", relation="parent"),
        ],
    )
    rows = tree_rows(graph)
    ids = [r.node_id for r in rows]
    assert ids[0] == ROOT_ID and set(ids) == {ROOT_ID, "A", "B"}
    assert any(r.repeated for r in rows)  # the cycle shows as a repeat marker, not a loop
    text = render_plain(graph)
    assert "(shown above)" in text


# --------------------------------------------------------------------------------------
# json, dot
# --------------------------------------------------------------------------------------


def test_json_round_trips_and_is_stable() -> None:
    graph = _fixture_graph()
    text = render_json(graph)
    assert text == render_json(graph)
    data = json.loads(text)
    assert list(data) == sorted(data)  # stable, sorted keys
    back = ProofGraph.model_validate(data)
    assert back == graph
    assert back.nodes["OBL-0002"].extra["closed_by_artifact"] == "PROOF-0001"


def test_dot_is_structurally_valid_and_escaped() -> None:
    graph = _fixture_graph()
    graph.nodes["CLAIM-0001"].title = 'Says "hi"\nand \\ more'
    dot = render_dot(graph)
    assert dot.startswith("digraph proof_tree {\n") and dot.rstrip().endswith("}")
    assert dot.count("{") == dot.count("}") == 1
    node_lines = [ln for ln in dot.splitlines() if re.match(r'^  "[^"]+" \[', ln)]
    assert len(node_lines) == len(graph.nodes)
    for ln in node_lines:
        assert ln.endswith("];")
    edge_lines = [ln for ln in dot.splitlines() if " -> " in ln]
    assert len(edge_lines) == len(graph.edges)
    assert all(re.match(r'^  "[^"]+" -> "[^"]+" \[label="[a-z_]+"', ln) for ln in edge_lines)
    assert 'label="closes"' in dot and 'label="specializes"' in dot
    assert '\\"hi\\"' in dot and "\\\\ more" in dot and "\\n" in dot
    assert "shape=hexagon" in dot and "shape=doubleoctagon" in dot and "shape=diamond" in dot
    assert "problem status UNSOLVED (derived from dossier artifacts)" in dot
    # every quoted node id has no raw newline or unescaped quote
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', dot):
        assert "\n" not in m.group(1)


# --------------------------------------------------------------------------------------
# filters and search
# --------------------------------------------------------------------------------------


def test_filter_graph_keeps_ancestors_and_root() -> None:
    graph = _fixture_graph()
    only_obligations = filter_graph(graph, kinds={"obligation"})
    assert set(only_obligations.nodes) == {
        ROOT_ID,
        "BRANCH-0001",
        "BRANCH-0002",
        "OBL-0001",
        "OBL-0002",
    }
    assert all(
        e.source_id in only_obligations.nodes and e.target_id in only_obligations.nodes
        for e in only_obligations.edges
    )
    closed = filter_graph(graph, kinds={"obligation"}, statuses={"CLOSED"})
    assert "OBL-0002" in closed.nodes and "OBL-0001" not in closed.nodes
    flat = filter_graph(graph, kinds={"evidence"}, keep_ancestors=False)
    assert set(flat.nodes) == {ROOT_ID, "EVID-0001"}
    untouched = filter_graph(graph)
    assert untouched == graph and untouched is not graph
    # the plain renderer applies the same filter
    text = render_plain(graph, kinds={"obligation"})
    assert "Filter: kinds=obligation" in text
    assert "OBL-0001" in text and "EVID-0001" not in text and "CLAIM-0001" not in text


def test_search_nodes_matches_id_text_and_bare_artifact_id() -> None:
    graph = _fixture_graph()
    assert [n.node_id for n in search_nodes(graph, "obl-")] == ["OBL-0001", "OBL-0002"]
    assert [n.node_id for n in search_nodes(graph, "10^6")] == ["EVID-0001"]
    assert [n.node_id for n in search_nodes(graph, "PROOF-0001")] == ["PROOF-0001@verifier"]
    assert search_nodes(graph, "   ") == []
    assert search_nodes(graph, "nothing-like-this") == []


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _init_campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["problem", "new", "For every n >= 1, P(n) holds."]).exit_code == 0
    res = runner.invoke(
        app, ["campaign", "start", "PROBLEM-0001", "--mode", "prove-or-refute", "--branches", "2"]
    )
    assert res.exit_code == 0, res.output
    return tmp_path / WORKSPACE_DIRNAME


def test_cli_tree_plain_json_dot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_campaign(tmp_path, monkeypatch)
    plain = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001"])
    assert plain.exit_code == 0, plain.output
    assert plain.output.startswith("Proof tree: PROBLEM-0001 (campaign CAMPAIGN-0001)")
    # The status line is derived from the dossier artifacts (a mock prover leaves a
    # sketch, so HEURISTIC_ONLY is as legitimate as UNSOLVED) and never a resolution.
    from opentorus.research.dossier.status_gate import derive_status

    ot = tmp_path / WORKSPACE_DIRNAME
    derived = derive_status(ot, "PROBLEM-0001").status
    assert derived in {"UNSOLVED", "HEURISTIC_ONLY", "EXPERIMENTAL_ONLY"}
    assert f"Problem status (derived from dossier artifacts): {derived}" in plain.output
    # a prove-or-refute portfolio always activates a proof branch (relation equivalent)
    assert re.search(r"BRANCH-\d{4} \[equivalent\] branch", plain.output), plain.output
    assert "CLAIM-0001 [equivalent] claim" in plain.output
    assert LEGEND in plain.output
    explicit = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001", "--plain"])
    assert explicit.output == plain.output
    js = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001", "--json"])
    assert js.exit_code == 0, js.output
    data = json.loads(js.output)
    graph = ProofGraph.model_validate(data)
    assert graph.campaign_id == "CAMPAIGN-0001" and ROOT_ID in graph.nodes
    assert graph.nodes["CLAIM-0001"].status == "unverified"
    assert graph.root_status.report_status == derived
    dot = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001", "--dot"])
    assert dot.exit_code == 0, dot.output
    assert dot.output.startswith("digraph proof_tree {") and '"BRANCH-0001" -> "ROOT"' in dot.output


def test_cli_tree_filters_depth_and_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_campaign(tmp_path, monkeypatch)
    only = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001", "--kind", "branch"])
    assert only.exit_code == 0, only.output
    assert "BRANCH-0001" in only.output and "CLAIM-0001 [" not in only.output
    depth0 = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001", "--depth", "0"])
    assert depth0.exit_code == 0 and "hidden below depth 0" in depth0.output
    out_path = tmp_path / "tree.dot"
    res = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001", "--dot", "--out", str(out_path)])
    assert res.exit_code == 0, res.output
    assert out_path.read_text(encoding="utf-8").startswith("digraph proof_tree {")
    assert "Wrote" in res.output
    js = runner.invoke(
        app, ["campaign", "tree", "CAMPAIGN-0001", "--json", "--status", "unverified"]
    )
    assert js.exit_code == 0
    kinds = {n["kind"] for n in json.loads(js.output)["nodes"].values()}
    assert kinds <= {"root", "claim", "branch"}


def test_cli_tree_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_campaign(tmp_path, monkeypatch)
    missing = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0042"])
    assert missing.exit_code == 1 and "No campaign 'CAMPAIGN-0042'" in missing.output
    bad = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001", "--json", "--dot"])
    assert bad.exit_code == 1 and "Choose one" in bad.output
    help_text = runner.invoke(app, ["campaign", "tree", "--help"]).output
    assert "never upgrades the problem's derived status" in " ".join(help_text.split())
    assert "merged with the dossier" in " ".join(help_text.split())
