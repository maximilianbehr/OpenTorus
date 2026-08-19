"""The proof tree: builder (real mock campaign + dossier ledgers), validation of
synthetic graphs (empty, one node, 500 nodes, deep chain, cycles, missing refs,
self-dependency, orphans, special-case root closing, malformed records), and the
structural guarantee that the tree layer never touches a claim status."""

from __future__ import annotations

import ast
import io
import json
import re
import time
import tokenize
from pathlib import Path

import pytest

from opentorus.campaign import proof_tree as proof_tree_pkg
from opentorus.campaign.models import (
    CampaignNodeState,
    CampaignSnapshot,
    ClosureMode,
    CostTotals,
    ObligationProposal,
    RootRelation,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.proof_tree.builder import build_proof_graph, verifier_node_id
from opentorus.campaign.proof_tree.models import (
    ROOT_ID,
    ProofEdge,
    ProofGraph,
    ProofNode,
    ProofNodeKind,
    ValidationIssue,
)
from opentorus.campaign.proof_tree.render import render_dot, render_json, render_plain
from opentorus.campaign.proof_tree.validation import find_cycles, issue_counts, validate_graph
from opentorus.campaign.store import open_campaign
from opentorus.campaign.workers import DEFAULT_WORKERS
from opentorus.campaign.workers.base import WorkerRuntime
from opentorus.research.dossier import store as dstore
from opentorus.research.dossier.claims import add_claim, add_evidence, add_proof_attempt
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
    **extra: object,
) -> ProofNode:
    return ProofNode(
        node_id=nid,
        kind=kind,
        title=nid,
        status=status,
        parents=parents or [],
        dependencies=deps or [],
        root_relation=relation,
        extra=dict(extra),
    )


def _graph(nodes: list[ProofNode], edges: list[ProofEdge] | None = None) -> ProofGraph:
    return ProofGraph(
        problem_id="PROBLEM-0001", nodes={n.node_id: n for n in nodes}, edges=edges or []
    )


def _root() -> ProofNode:
    return _node(ROOT_ID, ProofNodeKind.root, status="UNSOLVED", relation=RootRelation.equivalent)


def _codes(issues: list[ValidationIssue]) -> set[str]:
    return {i.code for i in issues}


class _SketchingWorker:
    """A librarian-slot worker that behaves like a prover: writes a primary sketch with
    one gap, links it to the primary claim, adds sketch evidence, and proposes the gap
    as an obligation. Offline; one step charged."""

    role = WorkerRole.librarian

    def __init__(self, body: str | None = None) -> None:
        self.body = body or (
            "## Main proof\n\nReduce to the base case, then induct. "
            "[GAP-1] the induction step is not justified.\n"
        )

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        pid = ctx.root_problem.problem_id
        primary = ctx.root_problem.primary_claim_id
        proof = add_proof_attempt(
            rt.ot_dir,
            pid,
            title="Induction sketch",
            body=self.body,
            gaps=["[GAP-1] the induction step is not justified"],
            claim_links=[primary] if primary else [],
        )
        if primary:
            add_evidence(
                rt.ot_dir,
                pid,
                primary,
                evidence_type="PROOF_SKETCH",
                summary="an induction sketch with one open gap",
                source_artifacts=[proof.id],
            )
        return WorkerResult(
            status="branch_done",
            usage=CostTotals(steps=1),
            obligations=[
                ObligationProposal(
                    statement="Justify the induction step",
                    gap_marker="GAP-1",
                    source_proof_id=proof.id,
                    root_relation=RootRelation.equivalent,
                    closure_modes=[
                        ClosureMode.nl_proof_referee_accepted,
                        ClosureMode.formal_proof,
                    ],
                )
            ],
            notes=["sketch written"],
        )


class _QuietWorker:
    """A worker that finishes its branch without touching the dossier, so the portfolio's
    other branches (proof, counterexample, ...) stay silent and the sketching worker in
    the librarian slot is the only source of artifacts."""

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        return WorkerResult(status="branch_done", notes=["quiet test worker"])


def run_sketch_campaign(tmp_path: Path, **worker_kwargs: object):
    """A completed prove-or-refute mock campaign in which exactly one branch (the
    literature branch, served by the sketching worker) produced a sketch, sketch
    evidence and one open obligation. Returns ``(root, ot, pid, snapshot)``."""
    root, ot, pid = make_workspace(tmp_path)
    registry = dict(DEFAULT_WORKERS)
    quiet_roles = (
        WorkerRole.prover,
        WorkerRole.falsifier,
        WorkerRole.formalizer,
        WorkerRole.symbolic_experimenter,
        WorkerRole.numerical_experimenter,
        WorkerRole.critic,
    )
    for role in quiet_roles:
        registry[role] = _QuietWorker()  # type: ignore[assignment]
    registry[WorkerRole.librarian] = _SketchingWorker(**worker_kwargs)  # type: ignore[arg-type]
    engine = make_engine(root, ot, worker_registry=registry)
    record = engine.start(pid, mode="prove-or-refute", branches=2)
    snapshot = open_campaign(ot, record.id).load().snapshot
    return root, ot, pid, snapshot


def sketch_branch_id(snapshot) -> str:  # noqa: ANN001
    """The id of the literature branch the sketching worker served."""
    return next(b.branch_id for b in snapshot.branches.values() if str(b.kind) == "literature")


# --------------------------------------------------------------------------------------
# builder on real state
# --------------------------------------------------------------------------------------


def test_empty_dossier_without_campaign_builds_a_root_only_graph(tmp_path: Path) -> None:
    _root_dir, ot, pid = make_workspace(tmp_path)
    graph = build_proof_graph(ot, pid, None)
    assert set(graph.nodes) == {ROOT_ID}
    assert graph.campaign_id is None
    root = graph.nodes[ROOT_ID]
    assert root.kind is ProofNodeKind.root
    assert "P(n)" in root.statement
    assert root.status == graph.root_status.report_status == "UNSOLVED"
    assert graph.edges == []
    assert not graph.has_errors(), graph.issues
    assert "derive_status" in " ".join(graph.root_status.derived_from)


def test_missing_dossier_is_an_issue_not_an_exception(tmp_path: Path) -> None:
    _root_dir, ot, _pid = make_workspace(tmp_path)
    graph = build_proof_graph(ot, "PROBLEM-0099", None)
    assert ROOT_ID in graph.nodes
    assert "malformed_node" in _codes(graph.issues)
    assert graph.root_status.label == "STATUS_UNCERTAIN"


def test_builder_merges_campaign_and_dossier(tmp_path: Path) -> None:
    _root_dir, ot, pid, snap = run_sketch_campaign(tmp_path)
    assert snap.obligations, "the sketching worker must have produced an obligation"
    graph = build_proof_graph(ot, pid, snap)
    kinds = {n.kind for n in graph.nodes.values()}
    assert {
        ProofNodeKind.root,
        ProofNodeKind.branch,
        ProofNodeKind.obligation,
        ProofNodeKind.claim,
        ProofNodeKind.evidence,
        ProofNodeKind.proof_attempt,
    } <= kinds
    assert graph.campaign_id == snap.campaign_id
    # branch under the root, obligation under the branch that produced the sketch
    sketch_branch = sketch_branch_id(snap)
    assert sketch_branch in graph.nodes and graph.nodes[sketch_branch].parents == [ROOT_ID]
    ob = graph.nodes["OBL-0001"]
    assert ob.parents == [sketch_branch] and ob.status == "open"
    assert ob.extra["closed_by_artifact"] is None
    assert ob.extra["gap_marker"] == "GAP-1"
    # the primary claim is attached to the root as equivalent
    primary = dstore.require_dossier(ot, pid).primary_claim_id
    assert primary and graph.nodes[primary].parents == [ROOT_ID]
    assert graph.nodes[primary].root_relation is RootRelation.equivalent
    assert graph.nodes[primary].extra["primary"] is True
    # proof attempt: gap count from the body, linked to the claim, provenance merged in
    proof = graph.nodes["PROOF-0001"]
    assert proof.kind is ProofNodeKind.proof_attempt
    assert proof.extra["gap_count"] == 1 and proof.extra["scope"] == "primary"
    assert proof.parents == [primary]
    assert proof.extra["campaign"]["branch_id"] == sketch_branch
    assert "campaign_node_id" in proof.extra["campaign"]
    # evidence nests under its claim with a supports edge
    ev_nodes = [n for n in graph.nodes.values() if n.kind is ProofNodeKind.evidence]
    assert ev_nodes and ev_nodes[0].parents == [primary]
    rels = {(e.source_id, e.target_id, e.relation) for e in graph.edges}
    assert (ev_nodes[0].node_id, primary, "supports") in rels
    assert ("PROOF-0001", primary, "supports") in rels
    assert ("OBL-0001", "PROOF-0001", "depends_on") in rels
    assert ("OBL-0001", sketch_branch, "parent") in rels
    # the obligation node id is reused from the snapshot; the campaign node is merged
    assert ob.extra["campaign_node_id"].startswith("NODE-")
    assert not graph.has_errors(), [i.message for i in graph.issues if i.severity == "error"]
    # root status is derived, never from campaign completion
    assert snap.status.value == "completed"
    assert graph.root_status.report_status in ("UNSOLVED", "HEURISTIC_ONLY")
    assert graph.nodes[ROOT_ID].extra["campaign"]["status"] == "completed"


def test_builder_verifier_ledger_nodes_and_verifies_edges(tmp_path: Path, accepted_proof) -> None:
    _root_dir, ot, pid = make_workspace(tmp_path)
    claim = add_claim(ot, pid, claim_type="CONJECTURE", statement="sin^2 + cos^2 = 1")
    proof_id = accepted_proof(ot, claim.id)
    # a rejected and an inconclusive ledger entry must appear too, and never verify
    from opentorus.jsonl import append_jsonl
    from opentorus.research.verifiers.proofs import ProofAttempt as LedgerAttempt
    from opentorus.research.verifiers.proofs import proofs_path

    append_jsonl(
        proofs_path(ot),
        LedgerAttempt(
            id="PROOF-0002",
            backend="sympy",
            accepted=False,
            source_path="proofs/PROOF-0002.json",
            output="not an identity",
            claim_id=claim.id,
            problem_id=pid,
        ),
    )
    append_jsonl(
        proofs_path(ot),
        LedgerAttempt(
            id="PROOF-0003",
            backend="lean4",
            accepted=False,
            inconclusive=True,
            source_path="proofs/PROOF-0003.lean",
            output="timeout",
        ),
    )
    add_evidence(
        ot,
        pid,
        claim.id,
        evidence_type="FORMAL_PROOF",
        summary="sympy accepted the identity",
        source_artifacts=[proof_id],
    )
    graph = build_proof_graph(ot, pid, None)
    ver = graph.nodes[verifier_node_id(proof_id)]
    assert ver.kind is ProofNodeKind.verification and ver.status == "accepted"
    assert ver.extra["artifact_id"] == proof_id and ver.extra["backend"] == "sympy"
    assert graph.nodes[verifier_node_id("PROOF-0002")].status == "rejected"
    assert graph.nodes[verifier_node_id("PROOF-0003")].status == "inconclusive"
    rels = {(e.source_id, e.target_id, e.relation) for e in graph.edges}
    assert (verifier_node_id(proof_id), "EVID-0001", "verifies") in rels
    assert not any(
        e.relation == "verifies"
        and e.source_id in (verifier_node_id("PROOF-0002"), verifier_node_id("PROOF-0003"))
        for e in graph.edges
    )
    # the claim moved to 'supported' by evidence, never verified; the tree copies that
    assert graph.nodes[claim.id].status == dstore.get_claim(ot, pid, claim.id).status  # type: ignore[union-attr]
    assert graph.nodes[claim.id].status != "verified"


def test_builder_reports_corrupt_ledger_lines_as_malformed_nodes(tmp_path: Path) -> None:
    _root_dir, ot, pid = make_workspace(tmp_path)
    add_claim(ot, pid, claim_type="OBSERVATION", statement="P(1) holds.")
    claims_path = dstore.dossier_dir(ot, pid) / "claims.jsonl"
    with claims_path.open("a", encoding="utf-8") as fh:
        fh.write('{"id": "CLAIM-0002", "type": "BOGUS", "statement": 1}\n')
        fh.write("this is not json\n")
    graph = build_proof_graph(ot, pid, None)  # must not raise
    malformed = [i for i in graph.issues if i.code == "malformed_node"]
    assert len(malformed) >= 2
    assert any("claims.jsonl line 2" in i.message for i in malformed)
    assert any("claims.jsonl line 3" in i.message for i in malformed)
    assert "CLAIM-0001" in graph.nodes  # the good record is still there


def test_builder_handles_unknown_campaign_node_kind_and_missing_branch(tmp_path: Path) -> None:
    _root_dir, ot, pid, snap = run_sketch_campaign(tmp_path)
    broken = snap.model_copy(deep=True)
    broken.campaign_nodes["NODE-0099"] = CampaignNodeState(
        node_id="NODE-0099", kind="gizmo", title="unplaceable"
    )
    broken.campaign_nodes["NODE-0098"] = CampaignNodeState(
        node_id="NODE-0098", kind="claim", artifact_id="CLAIM-0077", branch_id="BRANCH-0001"
    )
    broken.obligations["OBL-0001"].branch_id = "BRANCH-0042"
    graph = build_proof_graph(ot, pid, broken)  # never raises
    codes = _codes(graph.issues)
    assert "malformed_node" in codes  # gizmo
    assert "missing_ref" in codes  # CLAIM-0077 and BRANCH-0042
    assert "NODE-0099" not in graph.nodes
    assert graph.nodes["OBL-0001"].parents == [ROOT_ID]  # falls back to the root


def test_gap_marker_deletion_changes_the_proof_node_not_the_obligation(tmp_path: Path) -> None:
    """The obligation's status lives in the event log; erasing [GAP-1] from the sketch
    only changes the proof node's gap count."""
    _root_dir, ot, pid, snap = run_sketch_campaign(tmp_path)
    before = build_proof_graph(ot, pid, snap)
    assert before.nodes["PROOF-0001"].extra["gap_count"] == 1
    assert before.nodes["OBL-0001"].status == "open"
    proofs = dstore.list_proof_attempts(ot, pid)
    body_path = dstore.dossier_dir(ot, pid) / proofs[0].body_path  # type: ignore[operator]
    body_path.write_text(
        body_path.read_text(encoding="utf-8").replace("[GAP-1]", ""), encoding="utf-8"
    )
    proofs[0].gaps = []
    dstore.rewrite_proof_attempts(ot, pid, proofs)
    after = build_proof_graph(ot, pid, snap)
    assert after.nodes["PROOF-0001"].extra["gap_count"] == 0
    assert after.nodes["OBL-0001"].status == "open"
    assert after.nodes["OBL-0001"].extra["closed_by_artifact"] is None
    assert not any(e.relation == "closes" for e in after.edges)


# --------------------------------------------------------------------------------------
# validation on synthetic graphs
# --------------------------------------------------------------------------------------


def test_validate_empty_graph_reports_missing_root_and_renders() -> None:
    graph = ProofGraph(problem_id="PROBLEM-0001")
    issues = validate_graph(graph)
    assert _codes(issues) == {"malformed_node"}
    graph.issues.extend(issues)
    text = render_plain(graph)
    assert "(no nodes)" in text and "malformed_node" in text
    assert render_dot(graph).startswith("digraph proof_tree {")
    ProofGraph.model_validate(json.loads(render_json(graph)))


def test_validate_one_node_graph_is_clean() -> None:
    graph = _graph([_root()])
    assert validate_graph(graph) == []
    assert "ROOT" in render_plain(graph)


def test_missing_ref_self_dependency_and_invalid_relation() -> None:
    graph = _graph(
        [
            _root(),
            _node("CLAIM-0001", parents=[ROOT_ID], deps=["CLAIM-0009"]),
            _node("CLAIM-0002", parents=["CLAIM-0002"]),
            _node("REVIEW-0001", ProofNodeKind.review, status="pass"),
        ],
        [
            ProofEdge(source_id="CLAIM-0001", target_id="GHOST", relation="supports"),
            ProofEdge(source_id="CLAIM-0002", target_id="CLAIM-0002", relation="depends_on"),
            ProofEdge(source_id="REVIEW-0001", target_id="CLAIM-0001", relation="closes"),
            ProofEdge(source_id="CLAIM-0001", target_id="CLAIM-0002", relation="reviews"),
        ],
    )
    issues = validate_graph(graph)
    codes = _codes(issues)
    assert {"missing_ref", "self_dependency", "invalid_relation"} <= codes
    missing = [i for i in issues if i.code == "missing_ref"]
    assert any("CLAIM-0009" in i.node_ids for i in missing)
    assert any("GHOST" in i.node_ids for i in missing)
    invalid = [i for i in issues if i.code == "invalid_relation"]
    assert any("'closes' cannot target a claim node" in i.message for i in invalid)
    assert any("a review node cannot 'closes'" in i.message for i in invalid)
    assert any("'reviews'" in i.message for i in invalid)


def test_cycle_detection_is_iterative_and_reports_each_cycle_once() -> None:
    nodes = [
        _root(),
        _node("A", parents=["B"]),
        _node("B", parents=["C"]),
        _node("C", parents=["A"]),
    ]
    graph = _graph(nodes)
    cycles = find_cycles(graph)
    assert cycles == [["A", "B", "C"]]
    issues = validate_graph(graph)
    assert sum(1 for i in issues if i.code == "cycle") == 1
    # a 5000-deep chain must not hit the recursion limit
    chain = [_root()] + [
        _node(f"N{i}", parents=[f"N{i - 1}" if i else ROOT_ID]) for i in range(5000)
    ]
    assert find_cycles(_graph(chain)) == []


def test_deep_chain_validates_and_renders(tmp_path: Path) -> None:
    depth = 50
    nodes = [_root()]
    edges: list[ProofEdge] = []
    prev = ROOT_ID
    for i in range(depth):
        nid = f"OBL-{i:04d}"
        nodes.append(_node(nid, ProofNodeKind.obligation, status="open", parents=[prev]))
        edges.append(ProofEdge(source_id=nid, target_id=prev, relation="parent"))
        prev = nid
    graph = _graph(nodes, edges)
    assert validate_graph(graph) == []
    text = render_plain(graph)
    assert f"OBL-{depth - 1:04d}" in text
    deepest = [ln for ln in text.splitlines() if f"OBL-{depth - 1:04d}" in ln][0]
    assert deepest.startswith("  " * depth)
    shallow = render_plain(graph, max_depth=3)
    assert "hidden below depth 3" in shallow and f"OBL-{depth - 1:04d}" not in shallow


def test_large_synthetic_graph_validates_and_renders_quickly() -> None:
    nodes = [_root()]
    edges: list[ProofEdge] = []
    for b in range(10):
        bid = f"BRANCH-{b:04d}"
        nodes.append(
            _node(
                bid,
                ProofNodeKind.branch,
                status="active",
                parents=[ROOT_ID],
                relation=RootRelation.supporting,
            )
        )
        edges.append(ProofEdge(source_id=bid, target_id=ROOT_ID, relation="parent"))
        for o in range(49):
            oid = f"OBL-{b:02d}{o:02d}"
            nodes.append(_node(oid, ProofNodeKind.obligation, status="open", parents=[bid]))
            edges.append(ProofEdge(source_id=oid, target_id=bid, relation="parent"))
    graph = _graph(nodes, edges)
    assert len(graph.nodes) == 501
    started = time.perf_counter()
    issues = validate_graph(graph)
    plain = render_plain(graph)
    dot = render_dot(graph)
    js = render_json(graph)
    elapsed = time.perf_counter() - started
    assert issues == []
    assert plain.count(" obligation: ") == 490 and dot.count('-> "BRANCH-') == 490
    assert len(json.loads(js)["nodes"]) == 501
    assert elapsed < 5.0, f"500-node graph took {elapsed:.2f}s"


def test_orphan_artifact_is_a_warning() -> None:
    graph = _graph([_root(), _node("EVID-0001", ProofNodeKind.evidence, status="supports")])
    issues = validate_graph(graph)
    assert [(i.code, i.severity) for i in issues] == [("orphan_artifact", "warning")]
    # structural nodes are never orphans
    graph2 = _graph([_root(), _node("BRANCH-0001", ProofNodeKind.branch, status="proposed")])
    assert "orphan_artifact" not in _codes(validate_graph(graph2))


def test_special_case_marked_as_closing_the_root_is_an_error() -> None:
    special = _node(
        "OBL-0001",
        ProofNodeKind.obligation,
        status="closed",
        parents=[ROOT_ID],
        relation=RootRelation.special_case,
        closed_by_artifact="PROOF-0001",
    )
    graph = _graph(
        [
            _root(),
            special,
            _node(
                "PROOF-0001@verifier",
                ProofNodeKind.verification,
                status="accepted",
                relation=RootRelation.special_case,
            ),
        ],
        [
            ProofEdge(source_id="OBL-0001", target_id=ROOT_ID, relation="parent"),
            ProofEdge(source_id="PROOF-0001@verifier", target_id="OBL-0001", relation="closes"),
            ProofEdge(source_id="PROOF-0001@verifier", target_id=ROOT_ID, relation="verifies"),
        ],
    )
    issues = validate_graph(graph)
    special_issues = [i for i in issues if i.code == "special_case_root_closing"]
    assert special_issues
    assert any(i.severity == "error" and "verifies" in i.message for i in special_issues)
    # a relaxation whose status claims the root is settled
    relaxed = _node(
        "CLAIM-0002", status="settles-root", parents=[ROOT_ID], relation=RootRelation.relaxation
    )
    issues2 = validate_graph(_graph([_root(), relaxed]))
    assert any(i.code == "special_case_root_closing" and i.severity == "error" for i in issues2)
    # the same nodes with an equivalent relation are fine
    ok = _node("CLAIM-0003", status="verified", parents=[ROOT_ID], relation=RootRelation.equivalent)
    ok_issues = validate_graph(_graph([_root(), ok]))
    assert "special_case_root_closing" not in _codes(ok_issues)


def test_unsupported_transition_and_incompatible_assumptions() -> None:
    closed_without_artifact = _node(
        "OBL-0001", ProofNodeKind.obligation, status="closed", parents=[ROOT_ID]
    )
    bad_claim = _node("CLAIM-0001", status="proven", parents=[ROOT_ID])
    parent = ProofNode(
        node_id="BRANCH-0001",
        kind=ProofNodeKind.branch,
        status="active",
        parents=[ROOT_ID],
        assumption_context=["n is even"],
    )
    child = ProofNode(
        node_id="OBL-0002",
        kind=ProofNodeKind.obligation,
        status="open",
        parents=["BRANCH-0001"],
        assumption_context=["n is not even", "not n is even"],
    )
    graph = _graph([_root(), closed_without_artifact, bad_claim, parent, child])
    issues = validate_graph(graph)
    codes = _codes(issues)
    assert {"unsupported_transition", "incompatible_assumptions"} <= codes
    assert any(
        "closing artifact" in i.message for i in issues if i.code == "unsupported_transition"
    )
    assert any("'proven'" in i.message for i in issues if i.code == "unsupported_transition")
    assert issue_counts(issues)["incompatible_assumptions"] == 1


def test_duplicate_id_and_key_mismatch_are_reported() -> None:
    graph = ProofGraph(
        problem_id="PROBLEM-0001",
        nodes={
            ROOT_ID: _root(),
            "CLAIM-0001": _node("CLAIM-0001", parents=[ROOT_ID]),
            "claim-0001": _node("claim-0001", parents=[ROOT_ID]),
            "WRONG": _node("CLAIM-0002", parents=[ROOT_ID]),
        },
    )
    issues = validate_graph(graph)
    assert "duplicate_id" in _codes(issues)
    assert any(i.code == "malformed_node" and "WRONG" in i.node_ids for i in issues)


def test_validation_never_raises_on_hostile_extra() -> None:
    node = _node("OBL-0001", ProofNodeKind.obligation, status="closed", parents=[ROOT_ID])
    node.extra["closed_by_artifact"] = object()  # not JSON, not a string
    graph = _graph([_root(), node])
    issues = validate_graph(graph)  # must not raise
    assert isinstance(issues, list)


# --------------------------------------------------------------------------------------
# structural guarantee: the tree layer reads statuses, never writes them
# --------------------------------------------------------------------------------------

_STATUS_MUTATORS = (
    "set_claim_status",
    "verify_counterexample",
    "downgrade_claim_type",
    "record_validated_numerical",
    "append_status_change",
    "rewrite_claims",
    "update_claim(",
    "save_dossier",
    "rewrite_proof_attempts",
)


def _code_only(text: str) -> str:
    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


@pytest.mark.parametrize(
    "path", sorted(Path(proof_tree_pkg.__file__).parent.glob("*.py")), ids=lambda p: p.name
)
def test_proof_tree_modules_never_mutate_claim_or_problem_status(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    code = _code_only(text)
    for needle in _STATUS_MUTATORS:
        assert needle not in code, f"{path.name} uses {needle}"
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "dossier.claims" in node.module:
            raise AssertionError(f"{path.name} imports from dossier.claims: {node.module}")
    assert not re.search(r"\.write_text\(|open\([^)]*['\"]a['\"]", code), f"{path.name} writes"


def test_snapshot_never_carries_root_status(tmp_path: Path) -> None:
    _root_dir, ot, pid, snap = run_sketch_campaign(tmp_path)
    dumped = snap.model_dump(mode="json")
    assert "root_status" not in dumped and "report_status" not in dumped
    assert isinstance(snap, CampaignSnapshot)


def test_workspace_evidence_attributed_to_the_problem_is_a_node_not_a_missing_ref(
    tmp_path: Path,
) -> None:
    """The falsifier records bounded searches through the workspace evidence ledger
    (EVIDENCE-*), never the dossier's evidence/index.jsonl. Such evidence must appear
    as an evidence node under its claim (with a supports/contradicts edge) instead of
    surfacing as a ``missing_ref`` diagnostic — the first routed real run had two."""
    from opentorus.research.evidence import add_evidence as add_ws_evidence
    from opentorus.research.experiments import new_experiment

    _root_dir, ot, pid = make_workspace(tmp_path)
    claim = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for every n")
    exp = new_experiment(ot, "bounded search", template="counterexample_search", problem_id=pid)
    # the evidence ledger refuses the untouched template predicate: give it a real one
    run_py = ot / exp.path / "run.py"
    run_py.write_text(
        run_py.read_text().replace("return n * n >= n", "return n % 7 != 3"), encoding="utf-8"
    )
    ev, _advisory = add_ws_evidence(
        ot,
        claim.id,
        source_type="experiment",
        source_id=exp.id,
        summary="no counterexample below 10^6",
        direction="supports",
        strength="weak",
        problem_id=pid,
    )
    graph = build_proof_graph(ot, pid, None)
    node = graph.nodes[ev.id]
    assert node.kind is ProofNodeKind.evidence and node.source == "workspace"
    assert node.parents == [claim.id] and node.status == "supports"
    rels = {(e.source_id, e.target_id, e.relation) for e in graph.edges}
    assert (ev.id, claim.id, "supports") in rels
    assert not any(i.code == "missing_ref" and ev.id in i.node_ids for i in graph.issues)
    # workspace evidence of another problem stays out of this tree
    other = dstore.create_dossier(ot, "For every m, Q(m) holds.")
    add_ws_evidence(
        ot,
        claim.id,
        source_type="experiment",
        source_id=exp.id,
        summary="elsewhere",
        direction="supports",
        strength="weak",
        problem_id=other.id,
    )
    graph2 = build_proof_graph(ot, pid, None)
    assert [n for n in graph2.nodes.values() if n.source == "workspace"] == [graph2.nodes[ev.id]]
