"""The dashboard's pure view-models (no textual): overview, rows, detail, state
transitions, next-open-obligation — on synthetic graphs (empty, one node, 500 nodes,
deep chain, malformed refs, cycles, missing dependency) and on a real mock
prove-or-refute campaign; plus the read-only import-graph guarantee."""

from __future__ import annotations

import io
import re
import time
import tokenize
from pathlib import Path

import pytest

import opentorus.dashboard as dashboard_pkg
from opentorus.campaign.models import RootRelation
from opentorus.campaign.proof_tree.builder import build_proof_graph
from opentorus.campaign.proof_tree.models import (
    ROOT_ID,
    ProofEdge,
    ProofGraph,
    ProofNode,
    ProofNodeKind,
)
from opentorus.campaign.proof_tree.render import SYMBOL_OK, SYMBOL_OPEN, SYMBOL_SPECIAL
from opentorus.campaign.proof_tree.validation import validate_graph
from opentorus.campaign.store import open_campaign
from opentorus.dashboard.adapters import (
    PROBLEM_STATUS_SOURCE,
    DashboardData,
    NodeDetailModel,
    ViewState,
    build_detail,
    build_overview,
    build_rows,
    detail_lines,
    issue_lines,
    kind_cycle,
    load_dashboard_data,
    next_open_obligation,
    overview_from,
    overview_lines,
    status_cycle,
)
from opentorus.errors import OpenTorusError
from support.campaign import make_engine, make_workspace

# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _node(
    nid: str,
    kind: ProofNodeKind = ProofNodeKind.claim,
    *,
    status: str = "unverified",
    parents: list[str] | None = None,
    deps: list[str] | None = None,
    relation: RootRelation = RootRelation.unknown,
    title: str | None = None,
    extra: dict[str, object] | None = None,
) -> ProofNode:
    return ProofNode(
        node_id=nid,
        kind=kind,
        title=title if title is not None else nid,
        status=status,
        parents=parents or [],
        dependencies=deps or [],
        root_relation=relation,
        extra=dict(extra or {}),
    )


def _root() -> ProofNode:
    return _node(ROOT_ID, ProofNodeKind.root, status="UNSOLVED", relation=RootRelation.equivalent)


def _graph(nodes: list[ProofNode], *, validate: bool = True) -> ProofGraph:
    """A graph whose ``parent`` edges follow each node's ``parents`` list."""
    edges = [
        ProofEdge(source_id=n.node_id, target_id=p, relation="parent")
        for n in nodes
        for p in n.parents
    ]
    edges += [
        ProofEdge(source_id=n.node_id, target_id=d, relation="depends_on")
        for n in nodes
        for d in n.dependencies
    ]
    graph = ProofGraph(
        problem_id="PROBLEM-0001",
        campaign_id="CAMPAIGN-0001",
        nodes={n.node_id: n for n in nodes},
        edges=edges,
    )
    if validate:
        graph.issues.extend(validate_graph(graph))
    return graph


def _fixture_graph() -> ProofGraph:
    return _graph(
        [
            _root(),
            _node(
                "BRANCH-0001",
                ProofNodeKind.branch,
                status="active",
                parents=[ROOT_ID],
                relation=RootRelation.equivalent,
                title="Proof by induction",
                extra={
                    "kind": "proof",
                    "actual_cost": {
                        "steps": 3,
                        "tokens": 120,
                        "cost_usd": 0.5,
                        "wall_seconds": 2.0,
                    },
                    "work_items": [
                        {
                            "work_item_id": "WI-0001",
                            "role": "prover",
                            "status": "completed",
                            "steps": 3,
                            "tokens": 120,
                            "cost_usd": 0.5,
                            "routing_decision_id": "ROUTE-0001",
                        }
                    ],
                    "routing_decision_ids": ["ROUTE-0001"],
                },
            ),
            _node(
                "BRANCH-0002",
                ProofNodeKind.branch,
                status="suspended",
                parents=[ROOT_ID],
                relation=RootRelation.special_case,
                title="Small n",
            ),
            _node(
                "OBL-0001",
                ProofNodeKind.obligation,
                status="open",
                parents=["BRANCH-0001"],
                relation=RootRelation.equivalent,
                title="Induction step",
                extra={"closure_modes": ["formal_proof"], "quantifiers": ["for all n >= 1"]},
            ),
            _node(
                "OBL-0002",
                ProofNodeKind.obligation,
                status="closed",
                parents=["BRANCH-0002"],
                relation=RootRelation.special_case,
                title="n <= 5",
                extra={
                    "closed_by_artifact": "PROOF-0001",
                    "closed_by_mode": "exact_symbolic_certificate",
                },
            ),
            _node(
                "OBL-0003",
                ProofNodeKind.obligation,
                status="in_progress",
                parents=["BRANCH-0001"],
                relation=RootRelation.equivalent,
                title="Base case",
            ),
            _node(
                "CLAIM-0001",
                ProofNodeKind.claim,
                status="unverified",
                parents=[ROOT_ID],
                relation=RootRelation.equivalent,
                title="CONJECTURE CLAIM-0001",
            ),
            _node(
                "EVID-0001",
                ProofNodeKind.evidence,
                status="supports",
                parents=["CLAIM-0001"],
                title="EXPERIMENT evidence",
                extra={"evidence_type": "EXPERIMENT"},
            ),
        ]
    )


@pytest.fixture(scope="module")
def mock_campaign(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str, str]:
    """A completed prove-or-refute mock campaign: ``(root, ot_dir, problem_id, campaign_id)``."""
    tmp = tmp_path_factory.mktemp("dashboard-campaign")
    root, ot, pid = make_workspace(tmp)
    record = make_engine(root, ot).start(pid, mode="prove-or-refute", branches=2)
    return root, ot, pid, record.id


@pytest.fixture(scope="module")
def mock_data(mock_campaign: tuple[Path, Path, str, str]) -> DashboardData:
    _root, ot, _pid, cid = mock_campaign
    return load_dashboard_data(ot, cid)


# --------------------------------------------------------------------------------------
# read-only guarantee
# --------------------------------------------------------------------------------------


def _code_only(text: str) -> str:
    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


@pytest.mark.parametrize(
    "path",
    sorted(Path(dashboard_pkg.__file__).parent.glob("*.py")),
    ids=lambda p: p.name,
)
def test_dashboard_package_never_names_a_writer(path: Path) -> None:
    """Read-only by construction: no store append/snapshot write, no usage recording,
    no claim-status mutator, no file write in any dashboard module (code, not docs)."""
    code = _code_only(path.read_text(encoding="utf-8"))
    for needle in (
        "CampaignStore",  # never named: the loader goes through open_campaign(...).load()
        "write_snapshot",
        "record_usage",
        "set_claim_status",
        "verify_counterexample",
        "add_evidence",
        "add_claim",
        "atomic_write_text",
        "write_text",
        "append_jsonl",
        "rewrite_jsonl",
        "obligation_closed",
    ):
        assert not re.search(rf"\b{re.escape(needle)}\b", code), f"{path.name} names {needle}"
    # ``.append`` on anything that could be a store (lists are appended to freely)
    assert not re.search(r"store\s*\.\s*append", code), f"{path.name} appends to a store"
    assert not re.search(r"open\([^)]*['\"][aw]", code), f"{path.name} opens a file for writing"


def test_adapters_do_not_import_textual() -> None:
    import sys

    assert "opentorus.dashboard.adapters" in sys.modules
    text = Path(dashboard_pkg.__file__).parent.joinpath("adapters.py").read_text(encoding="utf-8")
    assert "textual" not in _code_only(text)


# --------------------------------------------------------------------------------------
# rows on synthetic graphs
# --------------------------------------------------------------------------------------


def test_one_node_graph_yields_one_root_row() -> None:
    graph = _graph([_root()])
    rows = build_rows(graph, expanded=set(graph.nodes))
    assert [r.node_id for r in rows] == [ROOT_ID]
    assert rows[0].depth == 0 and rows[0].has_children is False and rows[0].symbol == SYMBOL_OPEN
    assert "ROOT [equivalent] root" in rows[0].text()
    assert next_open_obligation(rows, None) is None
    assert kind_cycle(graph) == [None]
    assert status_cycle(graph) == [None]


def test_rows_show_symbols_depth_and_expand_markers() -> None:
    graph = _fixture_graph()
    rows = build_rows(graph, expanded=set(graph.nodes))
    by_id = {r.node_id: r for r in rows}
    assert [r.node_id for r in rows] == [
        ROOT_ID,
        "BRANCH-0001",
        "OBL-0001",
        "OBL-0003",
        "BRANCH-0002",
        "OBL-0002",
        "CLAIM-0001",
        "EVID-0001",
    ]
    assert by_id["OBL-0001"].depth == 2 and by_id["OBL-0001"].symbol == SYMBOL_OPEN
    assert by_id["OBL-0002"].symbol == SYMBOL_OK + SYMBOL_SPECIAL
    assert by_id["BRANCH-0001"].has_children and by_id["BRANCH-0001"].expanded
    assert by_id["BRANCH-0001"].text().lstrip().startswith("- ")
    assert not by_id["EVID-0001"].has_children
    assert "[special-case]" in by_id["OBL-0002"].text()


def test_collapsed_node_hides_its_subtree() -> None:
    graph = _fixture_graph()
    rows = build_rows(graph, expanded=set(graph.nodes) - {"BRANCH-0001"})
    ids = [r.node_id for r in rows]
    assert "OBL-0001" not in ids and "OBL-0003" not in ids
    assert "BRANCH-0002" in ids and "OBL-0002" in ids  # siblings unaffected
    branch = next(r for r in rows if r.node_id == "BRANCH-0001")
    assert branch.has_children and not branch.expanded
    assert branch.text().lstrip().startswith("+ ")
    # collapsing the root leaves the root line only
    assert [r.node_id for r in build_rows(graph, expanded=set())] == [ROOT_ID]


def test_filters_keep_ancestors_and_search_keeps_ancestors_of_hits() -> None:
    graph = _fixture_graph()
    obligations = build_rows(graph, expanded=set(graph.nodes), kinds={"obligation"})
    assert [r.node_id for r in obligations] == [
        ROOT_ID,
        "BRANCH-0001",
        "OBL-0001",
        "OBL-0003",
        "BRANCH-0002",
        "OBL-0002",
    ]
    closed = build_rows(graph, expanded=set(graph.nodes), kinds={"obligation"}, statuses={"closed"})
    assert [r.node_id for r in closed] == [ROOT_ID, "BRANCH-0002", "OBL-0002"]
    hits = build_rows(graph, expanded=set(graph.nodes), search="base case")
    assert [r.node_id for r in hits] == [ROOT_ID, "BRANCH-0001", "OBL-0003"]
    # a search ignores collapse state so a hit is never hidden under a collapsed parent
    hits_collapsed = build_rows(graph, expanded=set(), search="base case")
    assert [r.node_id for r in hits_collapsed] == [ROOT_ID, "BRANCH-0001", "OBL-0003"]
    assert build_rows(graph, expanded=set(graph.nodes), search="nothing-here") == [
        build_rows(graph, expanded=set(graph.nodes), search="nothing-here")[0]
    ]
    assert build_rows(graph, expanded=set(graph.nodes), search="   ") == build_rows(
        graph, expanded=set(graph.nodes)
    )


def test_next_open_obligation_cycles_through_open_and_in_progress() -> None:
    graph = _fixture_graph()
    rows = build_rows(graph, expanded=set(graph.nodes))
    assert next_open_obligation(rows, None) == "OBL-0001"
    assert next_open_obligation(rows, ROOT_ID) == "OBL-0001"
    assert next_open_obligation(rows, "OBL-0001") == "OBL-0003"
    assert next_open_obligation(rows, "OBL-0003") == "OBL-0001"  # wraps; OBL-0002 is closed
    assert next_open_obligation(rows, "EVID-0001") == "OBL-0001"
    only_closed = build_rows(graph, expanded=set(graph.nodes), statuses={"closed"})
    assert next_open_obligation(only_closed, None) is None


def test_kind_and_status_cycles_offer_what_the_graph_holds() -> None:
    graph = _fixture_graph()
    assert kind_cycle(graph) == [None, "branch", "obligation", "claim", "evidence"]
    cycle = status_cycle(graph)
    assert cycle[0] is None and cycle[1:4] == ["open", "in_progress", "closed"]
    assert set(cycle[1:]) == {
        "open",
        "in_progress",
        "closed",
        "suspended",
        "active",
        "unverified",
        "supports",
    }
    assert "unsolved" not in cycle  # the root's derived status is not a filter value
    state = ViewState()
    seen = [state.cycle_kind(graph) for _ in range(len(kind_cycle(graph)) + 1)]
    assert seen[0] == "branch" and seen[-1] == "branch" and None in seen
    seen_status = [state.cycle_status(graph) for _ in range(len(cycle))]
    assert seen_status[-1] is None


def test_view_state_transitions_are_pure_and_reversible() -> None:
    graph = _fixture_graph()
    state = ViewState()
    rows = state.rows(graph)
    assert len(rows) == 8 and state.current_id(rows) == ROOT_ID
    state.move(3, rows)
    assert state.current_id(rows) == "OBL-0003"
    state.move(100, rows)
    assert state.cursor == len(rows) - 1
    state.move(-100, rows)
    assert state.cursor == 0
    state.toggle("BRANCH-0001")
    assert state.collapsed == {"BRANCH-0001"} and len(state.rows(graph)) == 6
    state.toggle("BRANCH-0001")
    assert state.collapsed == set() and len(state.rows(graph)) == 8
    assert state.select("OBL-0002", rows) and state.current_id(rows) == "OBL-0002"
    assert not state.select("NOPE", rows) and state.current_id(rows) == "OBL-0002"
    state.set_search("  induction ")
    assert state.search == "induction"
    assert [r.node_id for r in state.rows(graph)] == [ROOT_ID, "BRANCH-0001", "OBL-0001"]
    state.set_search(None)
    assert state.search is None and "kind=all" in state.filter_text()
    state.live = True
    assert "live=on" in state.filter_text()


def test_large_graph_rows_build_fast() -> None:
    nodes = [_root()]
    for i in range(1, 501):
        parent = ROOT_ID if i <= 20 else f"N-{(i - 1) // 20:04d}"
        kind = ProofNodeKind.obligation if i % 3 == 0 else ProofNodeKind.claim
        status = "open" if i % 6 == 0 else "closed" if i % 3 == 0 else "unverified"
        nodes.append(_node(f"N-{i:04d}", kind, status=status, parents=[parent]))
    graph = _graph(nodes, validate=False)
    t0 = time.perf_counter()
    rows = build_rows(graph, expanded=set(graph.nodes))
    state = ViewState()
    for _ in range(3):
        state.cycle_kind(graph)
        state.rows(graph)
    state.kind_filter = None
    state.set_search("N-04")
    searched = state.rows(graph)
    elapsed = time.perf_counter() - t0
    assert len(rows) == 501
    assert all(r.node_id.startswith(("N-04", "ROOT", "N-00")) for r in searched)
    first_open = next_open_obligation(rows, None)
    assert first_open is not None and graph.nodes[first_open].status == "open"
    assert first_open == next(r.node_id for r in rows if r.status == "open")  # row order
    assert elapsed < 5.0, elapsed


def test_deep_chain_renders_every_level() -> None:
    nodes = [_root()]
    prev = ROOT_ID
    for i in range(1, 301):
        nid = f"L-{i:04d}"
        nodes.append(_node(nid, ProofNodeKind.lemma, parents=[prev]))
        prev = nid
    graph = _graph(nodes, validate=False)
    rows = build_rows(graph, expanded=set(graph.nodes))
    assert len(rows) == 301 and rows[-1].depth == 300
    collapsed = build_rows(graph, expanded=set(graph.nodes) - {"L-0100"})
    assert len(collapsed) == 101 and collapsed[-1].node_id == "L-0100"


def test_malformed_refs_and_cycles_produce_issues_and_rows_still_render(
    mock_data: DashboardData,
) -> None:
    graph = _graph(
        [
            _root(),
            _node("A", parents=["B"], deps=["MISSING-0001"]),
            _node("B", parents=["A"]),
            _node("GHOST", parents=["NOPE"]),
            _node("SELF", parents=[ROOT_ID], deps=["SELF"]),
        ]
    )
    codes = {i.code for i in graph.issues}
    assert {"cycle", "missing_ref", "self_dependency"} <= codes
    rows = build_rows(graph, expanded=set(graph.nodes))
    ids = [r.node_id for r in rows]
    assert set(ids) >= {ROOT_ID, "A", "B", "GHOST", "SELF"}
    assert any(r.repeated for r in rows)  # the cycle shows as a marker row, not a hang
    marker = next(r for r in rows if r.repeated)
    assert "(shown above)" in marker.text()
    overview = overview_from(mock_data.summary, graph)
    assert overview.graph_errors >= 3 and overview.graph_issue_counts["cycle"] >= 1
    lines = overview_lines(overview)
    assert any("graph issues:" in ln and "cycle=" in ln for ln in lines)
    panel = issue_lines(graph.issues)
    assert panel and panel[0].startswith("[error]")
    # the node detail lists the issues that name the node
    detail = build_detail(graph, "A", None)
    assert {i.code for i in detail.issues} >= {"cycle", "missing_ref"}
    ghost = build_detail(graph, "MISSING-0001", None)
    assert ghost.kind == "missing" and "dangling" in ghost.statement
    text = "\n".join(detail_lines(detail))
    assert "issue [error] missing_ref" in text


def test_missing_dependency_node_is_reported_not_raised() -> None:
    graph = _graph(
        [
            _root(),
            _node(
                "OBL-0001",
                ProofNodeKind.obligation,
                status="open",
                parents=[ROOT_ID],
                deps=["OBL-0099"],
            ),
        ]
    )
    assert any(i.code == "missing_ref" and "OBL-0099" in i.node_ids for i in graph.issues)
    rows = build_rows(graph, expanded=set(graph.nodes))
    assert [r.node_id for r in rows] == [ROOT_ID, "OBL-0001"]
    detail = build_detail(graph, "OBL-0001", None)
    assert detail.dependencies == ["OBL-0099"] and any(
        i.code == "missing_ref" for i in detail.issues
    )


# --------------------------------------------------------------------------------------
# detail on synthetic graphs
# --------------------------------------------------------------------------------------


def test_detail_carries_settlement_routing_cost_and_quantifiers() -> None:
    graph = _fixture_graph()
    branch = build_detail(graph, "BRANCH-0001", None)
    assert (
        branch.kind == "branch" and branch.objective == "" and branch.title == "Proof by induction"
    )
    assert branch.can_settle_root and branch.settlement_condition == "needs_justified_equivalence"
    assert branch.cost is not None and branch.cost.steps == 3 and branch.cost.tokens == 120
    assert [w.work_item_id for w in branch.work_items] == ["WI-0001"]
    assert [r.decision_id for r in branch.routing] == ["ROUTE-0001"]
    assert branch.children == ["OBL-0001", "OBL-0003"]
    text = "\n".join(detail_lines(branch))
    assert (
        "can settle the root" in text
        and "work item WI-0001" in text
        and "routing: ROUTE-0001" in text
    )
    special = build_detail(graph, "OBL-0002", None)
    assert not special.can_settle_root and "cannot settle the root" in "\n".join(
        detail_lines(special)
    )
    assert special.details["closed_by_artifact"] == "PROOF-0001"
    ob = build_detail(graph, "OBL-0001", None)
    assert ob.quantifiers == ["for all n >= 1"] and ob.details["closure_modes"] == "formal_proof"
    assert isinstance(ob, NodeDetailModel)


# --------------------------------------------------------------------------------------
# a real mock campaign
# --------------------------------------------------------------------------------------


def test_load_dashboard_data_reads_a_mock_campaign(
    mock_campaign: tuple[Path, Path, str, str], mock_data: DashboardData
) -> None:
    _root, ot, pid, cid = mock_campaign
    data = mock_data
    assert data.campaign_id == cid and data.problem_id == pid
    assert data.graph.campaign_id == cid and ROOT_ID in data.graph.nodes
    ov = data.overview
    assert ov.campaign_id == cid and ov.mode == "prove-or-refute" and ov.status == "completed"
    assert ov.problem_status_source == PROBLEM_STATUS_SOURCE
    assert ov.problem_report_status in {"UNSOLVED", "HEURISTIC_ONLY", "EXPERIMENTAL_ONLY"}
    assert ov.problem_report_status == data.graph.root_status.report_status
    assert ov.obligations_open >= 1 and ov.branch_counts
    assert [a.name for a in ov.budgets] == ["steps", "tokens", "cost", "wall"]
    assert ov.node_count == len(data.graph.nodes) and ov.edge_count == len(data.graph.edges)
    lines = overview_lines(ov)
    assert lines[0].startswith(f"Campaign {cid} on {pid}")
    assert any(ln.startswith("Problem status (derived from dossier artifacts):") for ln in lines)
    assert any("no node status and no campaign state ever upgrades it" in ln for ln in lines)
    assert any(ln.startswith("recent: EVT-") for ln in lines)
    # build_overview from disk equals the loader's overview
    again = build_overview(ot, cid)
    assert again.model_dump(exclude={"updated_at"}) == ov.model_dump(exclude={"updated_at"})
    partial = build_overview(ot, cid, snapshot=data.snapshot, summary=data.summary)
    assert partial.problem_report_status == ov.problem_report_status


def test_detail_fields_for_branch_obligation_claim_and_proof_nodes(
    mock_data: DashboardData,
) -> None:
    graph, snap = mock_data.graph, mock_data.snapshot
    branch_id = next(
        nid
        for nid, n in graph.nodes.items()
        if n.kind is ProofNodeKind.branch and n.extra.get("work_items")
    )
    branch = build_detail(graph, branch_id, snap, routing_records=mock_data.routing_records)
    assert branch.objective and branch.parents == [ROOT_ID]
    assert branch.cost is not None and branch.cost.steps >= 1
    assert branch.work_items and branch.work_items[0].role
    assert branch.details["kind"] in {"proof", "counterexample", "literature", "formalization"}
    obligation_id = next(
        nid for nid, n in graph.nodes.items() if n.kind is ProofNodeKind.obligation
    )
    ob = build_detail(graph, obligation_id, snap)
    assert ob.status in {"open", "in_progress"} and ob.details.get("closure_modes")
    assert ob.parents and ob.provenance.get("branch_id")
    assert ob.settlement_note
    claim = build_detail(graph, "CLAIM-0001", snap)
    assert claim.kind == "claim" and claim.details["primary"] == "True"
    assert claim.status == graph.nodes["CLAIM-0001"].status  # a copy of the ledger status
    assert claim.created_at is not None
    proof_id = next(
        (nid for nid, n in graph.nodes.items() if n.kind is ProofNodeKind.proof_attempt), None
    )
    assert proof_id is not None
    proof = build_detail(graph, proof_id, snap)
    assert proof.details["scope"] == "primary" and "gap_count" in proof.details
    assert proof.provenance.get("branch_id") and proof.cost is not None
    for detail in (branch, ob, claim, proof):
        text = "\n".join(detail_lines(detail))
        assert detail.node_id in text and "root relation:" in text and "created:" in text


def test_rows_and_obligation_jump_on_the_mock_campaign(mock_data: DashboardData) -> None:
    state = ViewState()
    rows = state.rows(mock_data.graph)
    assert rows[0].node_id == ROOT_ID and len(rows) == len(mock_data.graph.nodes)
    first = next_open_obligation(rows, None)
    assert first is not None and mock_data.graph.nodes[first].kind is ProofNodeKind.obligation
    assert state.select(first, rows) and state.current_id(rows) == first
    kinds = kind_cycle(mock_data.graph)
    assert "branch" in kinds and "obligation" in kinds and "claim" in kinds
    assert "open" in status_cycle(mock_data.graph)


def test_empty_campaign_without_branches(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    record = make_engine(root, ot).start(pid, mode="exploration", run=False)
    data = load_dashboard_data(ot, record.id)
    assert set(data.graph.nodes) == {ROOT_ID}
    assert data.overview.status == "created" and data.overview.branch_counts == {}
    assert data.overview.obligations_open == 0
    rows = ViewState().rows(data.graph)
    assert [r.node_id for r in rows] == [ROOT_ID]
    assert next_open_obligation(rows, None) is None
    detail = build_detail(data.graph, ROOT_ID, data.snapshot)
    assert detail.kind == "root" and detail.status == data.overview.problem_report_status
    assert kind_cycle(data.graph) == [None]


def test_missing_campaign_raises_a_clear_error(tmp_path: Path) -> None:
    _root, ot, _pid = make_workspace(tmp_path)
    with pytest.raises(OpenTorusError, match="No campaign 'CAMPAIGN-0042'"):
        load_dashboard_data(ot, "CAMPAIGN-0042")
    with pytest.raises(OpenTorusError, match="not a campaign id"):
        build_overview(ot, "nope")


def test_load_does_not_touch_the_campaign_files(
    mock_campaign: tuple[Path, Path, str, str],
) -> None:
    _root, ot, pid, cid = mock_campaign
    cdir = ot / "problems" / pid / "campaigns" / cid
    before = {
        p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in cdir.iterdir() if p.is_file()
    }
    data = load_dashboard_data(ot, cid)
    build_rows(data.graph, expanded=set(data.graph.nodes))
    for nid in data.graph.nodes:
        build_detail(data.graph, nid, data.snapshot)
    after = {
        p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in cdir.iterdir() if p.is_file()
    }
    assert after == before
    # and the snapshot on disk still replays (nothing was appended)
    assert open_campaign(ot, cid).verify_replay().matches
    graph_again = build_proof_graph(ot, pid, data.snapshot)
    assert set(graph_again.nodes) == set(data.graph.nodes)
