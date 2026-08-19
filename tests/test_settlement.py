"""Settlement rules: what a root relation can settle, and the single source of truth
for obligation closure. Every honest refusal is pinned here: numerical evidence
never closes, a model-written sketch does not close its own obligation, deleting
[GAP-n] markers closes nothing, a counterexample must name every root assumption,
rejected/inconclusive verifier runs are visible and never close, and campaign
completion never moves the derived root status."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.campaign.models import (
    ClosureMode,
    Obligation,
    ObligationStatus,
    RootRelation,
)
from opentorus.campaign.proof_tree.builder import build_proof_graph, verifier_node_id
from opentorus.campaign.proof_tree.models import (
    ROOT_ID,
    ProofEdge,
    ProofGraph,
    ProofNode,
    ProofNodeKind,
)
from opentorus.campaign.proof_tree.settlement import (
    RELATION_CAN_SETTLE,
    can_close_obligation,
    documented_gap_closure,
    ledger_proof_verdict,
    relation_settlement,
    root_status,
    special_case_marks_root,
    witness_satisfies_root_assumptions,
)
from opentorus.campaign.store import open_campaign
from opentorus.campaign.workers.verifier import closure_candidates
from opentorus.research.dossier import store as dstore
from opentorus.research.dossier.claims import (
    add_claim,
    add_evidence,
    add_proof_attempt,
    verify_counterexample,
)
from opentorus.research.dossier.experiments import create_experiment
from support.campaign import make_engine, make_workspace

# --------------------------------------------------------------------------------------
# relation rules
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relation", "condition"),
    [
        (RootRelation.equivalent, "needs_justified_equivalence"),
        (RootRelation.sufficient, "needs_verified_reduction_and_obligations"),
        (RootRelation.necessary, "needs_converse"),
        (RootRelation.counterexample_route, "needs_accepted_witness"),
        (RootRelation.special_case, None),
        (RootRelation.relaxation, None),
        (RootRelation.supporting, None),
        (RootRelation.unrelated, None),
        (RootRelation.unknown, None),
    ],
)
def test_each_relation_has_a_settlement_rule(relation: RootRelation, condition: str | None) -> None:
    assert RELATION_CAN_SETTLE[relation] == condition
    verdict = relation_settlement(relation)
    assert verdict.relation is relation
    assert verdict.can_settle is (condition is not None)
    assert verdict.condition == condition
    assert verdict.reason  # every rule explains itself
    assert relation_settlement(relation.value).can_settle is verdict.can_settle


def test_relation_table_covers_every_relation() -> None:
    assert set(RELATION_CAN_SETTLE) == set(RootRelation)


def test_special_case_and_relaxation_never_settle() -> None:
    for rel in (RootRelation.special_case, RootRelation.relaxation):
        verdict = relation_settlement(rel)
        assert verdict.can_settle is False
        assert "cannot settle the root" in verdict.reason


# --------------------------------------------------------------------------------------
# closure helpers
# --------------------------------------------------------------------------------------


def _ob(**overrides: object) -> Obligation:
    base: dict[str, object] = {
        "obligation_id": "OBL-0001",
        "campaign_id": "CAMPAIGN-0001",
        "branch_id": "BRANCH-0001",
        "statement": "sin(x)^2 + cos(x)^2 = 1",
        "closure_modes": [ClosureMode.formal_proof],
    }
    base.update(overrides)
    return Obligation(**base)  # type: ignore[arg-type]


def _another_accepted_proof(ot, claim_id: str | None = None) -> str:
    """A second, *different* accepted sympy certificate (the ledger caches identical
    sources under the first id, so the fixture alone cannot mint a second entry)."""
    import json as _json

    from opentorus.config import default_config
    from opentorus.research.verifiers.proofs import submit_proof
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    cert = _json.dumps({"lhs": "2*x", "rhs": "x + x", "relation": "eq", "vars": {"x": "real"}})
    attempt = submit_proof(
        ot, default_config(), "sympy", cert, claim_id=claim_id, verifier=SymPyVerifier()
    )
    assert attempt.accepted, attempt.output
    return attempt.id


def test_closed_obligation_and_no_modes_refuse_with_reason(tmp_path: Path) -> None:
    _root, ot, pid = make_workspace(tmp_path)
    closed = _ob(status=ObligationStatus.closed)
    verdict = can_close_obligation(ot, pid, closed)
    assert not verdict.allowed and "closed" in verdict.reason
    no_modes = _ob(closure_modes=[])
    verdict = can_close_obligation(ot, pid, no_modes)
    assert not verdict.allowed and "no closure modes" in verdict.reason


def test_accepted_proof_closes_with_formal_proof_mode(tmp_path: Path, accepted_proof) -> None:
    _root, ot, pid = make_workspace(tmp_path)
    proof_id = accepted_proof(ot)
    verdict = can_close_obligation(ot, pid, _ob(supporting_artifacts=[proof_id]))
    assert verdict.allowed
    assert verdict.mode is ClosureMode.formal_proof
    assert verdict.artifact_id == proof_id and verdict.check_id == proof_id
    # the certificate mode wins when listed and the backend matches
    both = _ob(
        supporting_artifacts=[proof_id],
        closure_modes=[ClosureMode.formal_proof, ClosureMode.exact_symbolic_certificate],
    )
    assert can_close_obligation(ot, pid, both).mode is ClosureMode.exact_symbolic_certificate
    # an obligation that only admits an SMT certificate is not closed by sympy
    smt_only = _ob(supporting_artifacts=[proof_id], closure_modes=[ClosureMode.smt_certificate])
    v = can_close_obligation(ot, pid, smt_only)
    assert not v.allowed and any("does not match" in d for d in v.details)
    # explicit artifact question
    assert can_close_obligation(ot, pid, _ob(), artifact_id=proof_id).allowed
    assert not can_close_obligation(ot, pid, _ob(), artifact_id="PROOF-0099").allowed


def test_ledger_four_checks_and_source_proof_id_is_never_looked_up_in_the_ledger(
    tmp_path: Path, accepted_proof
) -> None:
    from opentorus.jsonl import rewrite_jsonl
    from opentorus.research.verifiers.proofs import list_proofs, proofs_path

    _root, ot, pid = make_workspace(tmp_path)
    proof_id = accepted_proof(ot)
    ok, backend, reason = ledger_proof_verdict(ot, pid, proof_id)
    assert ok and backend == "sympy" and "accepted" in reason
    assert not ledger_proof_verdict(ot, pid, "PROOF-0042")[0]
    # a workspace ledger entry with the same id as the dossier sketch this obligation
    # came from must not close it: source_proof_id names the *dossier* attempt
    sketch = add_proof_attempt(ot, pid, title="sketch", body="[GAP-1] todo", gaps=["[GAP-1] todo"])
    assert sketch.id == proof_id  # the two id spaces collide, by construction
    verdict = can_close_obligation(ot, pid, _ob(source_proof_id=sketch.id, supporting_artifacts=[]))
    assert not verdict.allowed
    # ... nor via supporting_artifacts (a live run closed thirteen gaps that way)
    verdict = can_close_obligation(ot, pid, _ob(supporting_artifacts=[sketch.id]))
    assert not verdict.allowed and any(
        "names a dossier proof attempt" in d for d in verdict.details
    )
    # recorded under another problem -> refused with the reason (a second ledger entry,
    # whose id no sketch shares)
    second = _another_accepted_proof(ot)
    assert second != sketch.id
    proofs = list_proofs(ot)
    proofs[-1].problem_id = "PROBLEM-0099"
    rewrite_jsonl(proofs_path(ot), proofs)
    verdict = can_close_obligation(ot, pid, _ob(supporting_artifacts=[second]))
    assert not verdict.allowed and any("recorded under PROBLEM-0099" in d for d in verdict.details)


def test_rejected_and_inconclusive_verifier_runs_are_visible_and_never_close(
    tmp_path: Path,
) -> None:
    from opentorus.jsonl import append_jsonl
    from opentorus.research.verifiers.proofs import ProofAttempt as LedgerAttempt
    from opentorus.research.verifiers.proofs import proofs_path

    _root, ot, pid = make_workspace(tmp_path)
    append_jsonl(
        proofs_path(ot),
        LedgerAttempt(
            id="PROOF-0001",
            backend="sympy",
            accepted=False,
            source_path="proofs/PROOF-0001.json",
            output="counterexample x=1",
        ),
    )
    append_jsonl(
        proofs_path(ot),
        LedgerAttempt(
            id="PROOF-0002",
            backend="lean4",
            accepted=False,
            inconclusive=True,
            source_path="proofs/PROOF-0002.lean",
            output="timeout after 60s",
        ),
    )
    for pid_ in ("PROOF-0001", "PROOF-0002"):
        verdict = can_close_obligation(ot, pid, _ob(supporting_artifacts=[pid_]))
        assert not verdict.allowed, pid_
    assert any(
        "REJECTED" in d
        for d in can_close_obligation(ot, pid, _ob(supporting_artifacts=["PROOF-0001"])).details
    )
    assert any(
        "inconclusive" in d
        for d in can_close_obligation(ot, pid, _ob(supporting_artifacts=["PROOF-0002"])).details
    )
    graph = build_proof_graph(ot, pid, None)
    assert graph.nodes[verifier_node_id("PROOF-0001")].status == "rejected"
    assert graph.nodes[verifier_node_id("PROOF-0002")].status == "inconclusive"
    assert not any(e.relation in ("verifies", "closes") for e in graph.edges)


def test_numerical_observation_never_closes_an_obligation(tmp_path: Path) -> None:
    _root, ot, pid = make_workspace(tmp_path)
    claim = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for all n")
    exp = create_experiment(ot, pid, title="check n<=1000", command="python check.py")
    ev, _ = add_evidence(
        ot,
        pid,
        claim.id,
        evidence_type="EXPERIMENT",
        summary="holds for n <= 1000",
        source_artifacts=[exp.experiment_id],
    )
    ob = _ob(
        supporting_artifacts=[ev.id, exp.experiment_id, claim.id],
        dependencies=[claim.id],
        closure_modes=list(ClosureMode),
    )
    verdict = can_close_obligation(ot, pid, ob)
    assert not verdict.allowed
    assert "stays open" in verdict.reason
    proposals, notes = closure_candidates(ot, pid, [ob])
    assert proposals == [] and any("stays open" in n for n in notes)
    # the claim is at most 'supported'; the tree copies that and never upgrades it
    graph = build_proof_graph(ot, pid, None)
    assert graph.nodes[claim.id].status in ("unverified", "supported")
    assert graph.root_status.report_status != "SOLVED"


def _sketch_dossier(tmp_path: Path, body: str, *, link_claim: bool = True):
    """A dossier with a primary CONJECTURE claim and a primary sketch (returns ids)."""
    root, ot, pid = make_workspace(tmp_path)
    claim = add_claim(ot, pid, claim_type="CONJECTURE", statement="For every n >= 1, P(n) holds.")
    dossier = dstore.require_dossier(ot, pid)
    dossier.primary_claim_id = claim.id
    dstore.save_dossier(ot, dossier)
    proof = add_proof_attempt(
        ot,
        pid,
        title="Induction sketch",
        body=body,
        gaps=["[GAP-1] the induction step is not justified"] if "[GAP-1]" in body else [],
        claim_links=[claim.id] if link_claim else [],
    )
    return root, ot, pid, claim, proof


_GAPPY = "## Main proof\n\nInduct on n. [GAP-1] the induction step is not justified.\n"


def test_model_written_sketch_does_not_close_its_own_obligation(tmp_path: Path) -> None:
    _root, ot, pid, claim, proof = _sketch_dossier(tmp_path, _GAPPY)
    ob = _ob(
        source_proof_id=proof.id,
        gap_marker="GAP-1",
        closure_modes=[ClosureMode.nl_proof_referee_accepted, ClosureMode.formal_proof],
    )
    verdict = can_close_obligation(ot, pid, ob)
    assert not verdict.allowed
    assert any("open gaps remain" in d for d in verdict.details)
    # a gap-free sketch that overclaims is blocked by the referee, not accepted
    proofs = dstore.list_proof_attempts(ot, pid)
    body_path = dstore.dossier_dir(ot, pid) / proofs[0].body_path  # type: ignore[operator]
    body_path.write_text(
        "## Main proof\n\nThis proves the conjecture. [GAP-1] closed: by induction.\n",
        encoding="utf-8",
    )
    proofs[0].gaps = []
    dstore.rewrite_proof_attempts(ot, pid, proofs)
    verdict = can_close_obligation(ot, pid, ob)
    assert not verdict.allowed
    assert any("referee verdict" in d for d in verdict.details)
    # exploration-scope attempts are never the dossier answer
    explo = add_proof_attempt(
        ot, pid, title="side idea", body="no gaps here", scope="exploration", claim_links=[claim.id]
    )
    v2 = can_close_obligation(
        ot,
        pid,
        _ob(source_proof_id=explo.id, closure_modes=[ClosureMode.nl_proof_referee_accepted]),
    )
    assert not v2.allowed and any("exploration-scope" in d for d in v2.details)


def test_deleting_gap_markers_does_not_close_the_obligation(tmp_path: Path) -> None:
    """Silently erasing [GAP-1] and clearing the recorded gaps closes nothing; a
    documented closure ('[GAP-1] closed: ...') under a passing referee does."""
    _root, ot, pid, claim, proof = _sketch_dossier(tmp_path, _GAPPY)
    ob = _ob(
        source_proof_id=proof.id,
        gap_marker="GAP-1",
        dependencies=[claim.id],
        closure_modes=[ClosureMode.nl_proof_referee_accepted],
    )
    assert not can_close_obligation(ot, pid, ob).allowed
    proofs = dstore.list_proof_attempts(ot, pid)
    body_path = dstore.dossier_dir(ot, pid) / proofs[0].body_path  # type: ignore[operator]
    erased = body_path.read_text(encoding="utf-8").replace("[GAP-1]", "")
    body_path.write_text(erased, encoding="utf-8")
    proofs[0].gaps = []
    dstore.rewrite_proof_attempts(ot, pid, proofs)
    assert documented_gap_closure(erased, "GAP-1") is False
    verdict = can_close_obligation(ot, pid, ob)
    assert not verdict.allowed
    assert any("deleting a [GAP-n] marker does not close" in d for d in verdict.details)
    # the tree agrees: the proof node lost its gap, the obligation stays open
    graph = build_proof_graph(ot, pid, None)
    assert graph.nodes[proof.id].extra["gap_count"] == 0
    # ...whereas a documented closure is a real candidate for the referee route
    body_path.write_text(
        "## Main proof\n\nInduct on n; the step follows from monotonicity.\n\n"
        "## Gaps closed\n\n[GAP-1] closed: the induction step is justified above.\n",
        encoding="utf-8",
    )
    assert documented_gap_closure(body_path.read_text(encoding="utf-8"), "GAP-1") is True
    verdict = can_close_obligation(ot, pid, ob)
    assert verdict.allowed and verdict.mode is ClosureMode.nl_proof_referee_accepted
    assert verdict.artifact_id == proof.id
    assert "not machine-checked" in verdict.reason
    # closing an obligation this way changes no claim status and no root status
    assert dstore.get_claim(ot, pid, claim.id).status == "unverified"  # type: ignore[union-attr]
    assert root_status(ot, pid).report_status in ("UNSOLVED", "HEURISTIC_ONLY")


def test_referee_route_requires_the_proof_to_name_the_obligations_claim(tmp_path: Path) -> None:
    body = "## Main proof\n\nDirect.\n\n## Gaps closed\n\n[GAP-1] closed: trivial case handled.\n"
    _root, ot, pid, claim, proof = _sketch_dossier(tmp_path, body, link_claim=False)
    ob = _ob(
        source_proof_id=proof.id,
        gap_marker="GAP-1",
        closure_modes=[ClosureMode.nl_proof_referee_accepted],
    )
    verdict = can_close_obligation(ot, pid, ob)
    assert not verdict.allowed
    assert any("do not name the obligation's claim" in d for d in verdict.details)


def test_verified_counterexample_must_name_every_root_assumption(
    tmp_path: Path, accepted_proof
) -> None:
    _root, ot, pid = make_workspace(tmp_path)
    dstore.add_assumption(ot, pid, "n is a positive integer")
    dstore.add_assumption(ot, pid, "P is monotone")
    primary = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for all n")
    partial = add_claim(
        ot,
        pid,
        claim_type="COUNTEREXAMPLE_CANDIDATE",
        statement="n = 7 violates P",
        depends_on=[primary.id],
    )
    complete = add_claim(
        ot,
        pid,
        claim_type="COUNTEREXAMPLE_CANDIDATE",
        statement="n = 11 violates P",
        depends_on=[primary.id],
    )
    proof_id = accepted_proof(ot)
    for c in (partial, complete):
        ev, _ = add_evidence(
            ot,
            pid,
            c.id,
            evidence_type="FORMAL_PROOF",
            summary="checked",
            source_artifacts=[proof_id],
        )
        verify_counterexample(
            ot,
            pid,
            c.id,
            verification_artifact=ev.id,
            summary=(
                "witness checked: n is a positive integer"
                if c is partial
                else "witness checked: n is a positive integer; P is monotone on the instance"
            ),
        )
    partial_rec = dstore.get_claim(ot, pid, partial.id)
    complete_rec = dstore.get_claim(ot, pid, complete.id)
    assert partial_rec is not None and complete_rec is not None
    assert partial_rec.type == complete_rec.type == "COUNTEREXAMPLE_VERIFIED"
    ok, missing = witness_satisfies_root_assumptions(ot, pid, partial_rec)
    assert not ok and missing == ["P is monotone"]
    ok2, missing2 = witness_satisfies_root_assumptions(ot, pid, complete_rec)
    assert ok2 and missing2 == []
    mode = [ClosureMode.accepted_counterexample_certificate]
    refused = can_close_obligation(
        ot, pid, _ob(supporting_artifacts=[partial.id], closure_modes=mode)
    )
    assert not refused.allowed
    assert any(
        "does not name the root assumption" in d and "P is monotone" in d for d in refused.details
    )
    allowed = can_close_obligation(
        ot, pid, _ob(supporting_artifacts=[complete.id], closure_modes=mode)
    )
    assert allowed.allowed and allowed.mode is ClosureMode.accepted_counterexample_certificate
    assert allowed.artifact_id == complete.id
    # a candidate (unverified) counterexample never closes
    cand = add_claim(ot, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="n = 13?")
    v = can_close_obligation(ot, pid, _ob(supporting_artifacts=[cand.id], closure_modes=mode))
    assert not v.allowed and any("not a verified counterexample" in d for d in v.details)
    # in the tree the verified counterexample refutes the primary claim and the root
    graph = build_proof_graph(ot, pid, None)
    rels = {(e.source_id, e.target_id, e.relation) for e in graph.edges}
    assert (complete.id, primary.id, "refutes") in rels
    assert graph.nodes[complete.id].kind is ProofNodeKind.counterexample


def test_literature_route_needs_accepted_reference_and_targeted_check(tmp_path: Path) -> None:
    from opentorus.research.papers import acquire_paper, read_paper
    from opentorus.research.sources.base import SourceRecord
    from opentorus.research.theorems import store as thm_store
    from opentorus.research.theorems.models import (
        ApplicabilityCheck,
        ApplicabilityResult,
        SourceLocator,
        TheoremReference,
    )

    _root, ot, pid = make_workspace(tmp_path)
    claim = add_claim(
        ot, pid, claim_type="CONJECTURE", statement="every element has order dividing n"
    )
    record = SourceRecord(source="arxiv", title="Finite groups", arxiv_id="2401.00001")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    read_paper(
        ot,
        paper.id,
        page_extractor=lambda p: [
            "2 Main results\nTheorem 2.1. Let G be a finite group of order n. Then every element "
            "of G has order dividing n.\n"
        ],
    )
    ref = thm_store.add_reference(
        ot,
        TheoremReference(
            paper_id=paper.id,
            locator=SourceLocator(paper_id=paper.id, label="Theorem 2.1"),
            theorem_label="Theorem 2.1",
            problem_id=pid,
        ),
    )
    mode = [ClosureMode.accepted_literature_theorem]
    ob = _ob(supporting_artifacts=[ref.id], dependencies=[claim.id], closure_modes=mode)
    v = can_close_obligation(ot, pid, ob)
    assert not v.allowed and any("needs accepted" in d for d in v.details)
    thm_store.set_review_status(ot, ref.id, "accepted", "checked by hand")
    v = can_close_obligation(ot, pid, ob)
    assert not v.allowed and any("no accepted applicability check" in d for d in v.details)
    thm_store.add_applicability_check(
        ot,
        ApplicabilityCheck(
            theorem_reference_id=ref.id,
            problem_id=pid,
            target_id="CLAIM-0099",
            result=ApplicabilityResult.accepted,
        ),
    )
    v = can_close_obligation(ot, pid, ob)
    assert not v.allowed and any("not the obligation or its claim" in d for d in v.details)
    check = thm_store.add_applicability_check(
        ot,
        ApplicabilityCheck(
            theorem_reference_id=ref.id,
            problem_id=pid,
            target_id=claim.id,
            result=ApplicabilityResult.accepted,
        ),
    )
    v = can_close_obligation(ot, pid, ob)
    assert v.allowed and v.mode is ClosureMode.accepted_literature_theorem
    assert v.check_id == check.id
    # nothing about the claim moved
    assert dstore.get_claim(ot, pid, claim.id).status == "unverified"  # type: ignore[union-attr]


# --------------------------------------------------------------------------------------
# root status and structural checks
# --------------------------------------------------------------------------------------


def test_campaign_completion_leaves_root_status_unchanged(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    before = root_status(ot, pid)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="prove-or-refute", branches=4)
    snap = open_campaign(ot, record.id).load().snapshot
    assert snap.status.value == "completed"
    after = root_status(ot, pid)
    # The campaign's workers may legitimately add support-only artifacts (a sketch turns
    # UNSOLVED into HEURISTIC_ONLY), but completion itself never settles anything: the
    # status is whatever the dossier artifacts derive to, recomputed independently of
    # the campaign, and it is never a resolving label.
    from opentorus.research.dossier.status_gate import derive_status

    assert before.report_status == "UNSOLVED"
    assert after.report_status == derive_status(ot, pid).status
    assert after.report_status in {"UNSOLVED", "HEURISTIC_ONLY", "EXPERIMENTAL_ONLY"}
    assert after.label not in {"GENERAL_CONJECTURE_PROVED", "GENERAL_CONJECTURE_REFUTED"}
    assert "classify_outcome" in " ".join(after.derived_from)
    assert not any("campaign" in d.lower() for d in after.derived_from)
    graph = build_proof_graph(ot, pid, snap)
    assert graph.root_status.report_status == after.report_status
    assert graph.nodes[ROOT_ID].status == after.report_status


def test_root_status_never_raises_on_a_missing_dossier(tmp_path: Path) -> None:
    _root, ot, _pid = make_workspace(tmp_path)
    view = root_status(ot, "PROBLEM-0042")
    assert view.label == "STATUS_UNCERTAIN" and view.report_status == "UNSOLVED"


def test_special_case_marks_root_flags_only_non_settling_relations() -> None:
    root = ProofNode(node_id=ROOT_ID, kind=ProofNodeKind.root, status="UNSOLVED")
    special = ProofNode(
        node_id="CLAIM-0001",
        kind=ProofNodeKind.claim,
        status="verified",
        root_relation=RootRelation.special_case,
        parents=[ROOT_ID],
    )
    equivalent = ProofNode(
        node_id="CLAIM-0002",
        kind=ProofNodeKind.claim,
        status="verified",
        root_relation=RootRelation.equivalent,
        parents=[ROOT_ID],
    )
    graph = ProofGraph(
        problem_id="PROBLEM-0001",
        nodes={n.node_id: n for n in (root, special, equivalent)},
        edges=[
            ProofEdge(source_id="CLAIM-0001", target_id=ROOT_ID, relation="verifies"),
            ProofEdge(source_id="CLAIM-0002", target_id=ROOT_ID, relation="verifies"),
        ],
    )
    issues = special_case_marks_root(graph)
    assert len(issues) == 1
    assert issues[0].node_ids[0] == "CLAIM-0001" and issues[0].severity == "error"
    flagged = ProofNode(
        node_id="OBL-0001",
        kind=ProofNodeKind.obligation,
        status="open",
        root_relation=RootRelation.relaxation,
        extra={"settles_root": True},
    )
    graph2 = ProofGraph(problem_id="PROBLEM-0001", nodes={ROOT_ID: root, "OBL-0001": flagged})
    assert [i.severity for i in special_case_marks_root(graph2)] == ["error"]


def test_a_sketch_id_cited_as_support_is_never_resolved_in_the_verifier_ledger(
    tmp_path: Path, accepted_proof
) -> None:
    """The live failure: the prover had sympy accept ``1/4 >= (1/2)**2`` as ledger
    PROOF-0001 for the primary claim; the sketch is *also* PROOF-0001 (dossier space) and
    every gap obligation cites the sketch as its supporting artifact. Thirteen gaps
    "closed" as exact symbolic certificates. A supporting-artifact id that names a
    dossier proof attempt must never be looked up in the ledger — via the obligation's
    own citations, via the verifier-coordinator's proposals, or as an explicit
    "can PROOF-0001 close it?" question."""
    from opentorus.research.dossier.claims import add_claim

    _root, ot, pid = make_workspace(tmp_path)
    claim = add_claim(ot, pid, claim_type="CONJECTURE", statement="Sidorenko holds for all H")
    ledger_id = accepted_proof(ot, claim.id)  # a real, accepted, *trivial* certificate
    sketch = add_proof_attempt(
        ot, pid, title="sketch", body="[GAP-1] general case", gaps=["[GAP-1] general case"]
    )
    assert sketch.id == ledger_id  # both PROOF-0001: the id spaces collide by construction
    ob = _ob(
        supporting_artifacts=[sketch.id],
        dependencies=[claim.id],
        source_proof_id=sketch.id,
        gap_marker="GAP-1",
        closure_modes=[
            ClosureMode.nl_proof_referee_accepted,
            ClosureMode.formal_proof,
            ClosureMode.smt_certificate,
            ClosureMode.exact_symbolic_certificate,
        ],
    )
    verdict = can_close_obligation(ot, pid, ob)
    assert not verdict.allowed, verdict
    assert any("names a dossier proof attempt" in d for d in verdict.details)
    assert not can_close_obligation(ot, pid, ob, artifact_id=sketch.id).allowed
    proposals, _notes = closure_candidates(ot, pid, [ob])
    assert proposals == []


def test_a_certificate_recorded_for_another_claim_does_not_close_an_obligation(
    tmp_path: Path, accepted_proof
) -> None:
    from opentorus.research.dossier.claims import add_claim

    _root, ot, pid = make_workspace(tmp_path)
    mine = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for all n")
    other = add_claim(ot, pid, claim_type="LEMMA_ATTEMPT", statement="an identity")
    ledger_id = accepted_proof(ot, other.id)
    ob = _ob(supporting_artifacts=[ledger_id], dependencies=[mine.id])
    verdict = can_close_obligation(ot, pid, ob)
    assert not verdict.allowed
    assert any(f"recorded for {other.id}" in d for d in verdict.details)
    # the same certificate closes an obligation about the claim it was recorded for
    assert can_close_obligation(
        ot, pid, _ob(supporting_artifacts=[ledger_id], dependencies=[other.id])
    ).allowed


def test_audit_closures_flags_closures_the_current_rules_refuse(
    tmp_path: Path, accepted_proof
) -> None:
    """A closure is an append-only event; when the rules tighten (or a bug is fixed)
    the audit makes the stale closure visible instead of trusting the snapshot."""
    from opentorus.campaign.proof_tree.settlement import audit_closures

    _root, ot, pid = make_workspace(tmp_path)
    accepted_proof(ot)  # ledger PROOF-0001 — the id the sketch below will share
    good_id = _another_accepted_proof(ot)  # ledger PROOF-0002: no sketch shares it
    sketch = add_proof_attempt(ot, pid, title="sketch", body="[GAP-1] todo", gaps=["[GAP-1] todo"])
    assert sketch.id != good_id
    justified = _ob(
        obligation_id="OBL-0001",
        status=ObligationStatus.closed,
        supporting_artifacts=[good_id],
        closed_by_artifact=good_id,
        closed_by_mode=ClosureMode.formal_proof,
    )
    stale = _ob(
        obligation_id="OBL-0002",
        status=ObligationStatus.closed,
        supporting_artifacts=[sketch.id],
        closed_by_artifact=sketch.id,
        closed_by_mode=ClosureMode.exact_symbolic_certificate,
        closure_modes=[ClosureMode.exact_symbolic_certificate],
    )
    bare = _ob(obligation_id="OBL-0003", status=ObligationStatus.closed, closed_by_artifact=None)
    still_open = _ob(obligation_id="OBL-0004")
    audits = {
        a.obligation_id: a for a in audit_closures(ot, pid, [justified, stale, bare, still_open])
    }
    assert set(audits) == {"OBL-0001", "OBL-0002", "OBL-0003"}  # open ones are not audited
    assert audits["OBL-0001"].justified
    assert not audits["OBL-0002"].justified and "dossier proof attempt" in audits["OBL-0002"].reason
    assert (
        not audits["OBL-0003"].justified
        and "without a recorded artifact" in audits["OBL-0003"].reason
    )
    # the proof tree surfaces the stale closure as an error issue on that node
    from datetime import UTC, datetime

    from opentorus.campaign.models import CampaignSnapshot

    now = datetime(2026, 1, 1, tzinfo=UTC)
    snap = CampaignSnapshot(
        campaign_id="CAMPAIGN-0001",
        problem_id=pid,
        mode="prove-or-refute",
        created_at=now,
        updated_at=now,
    )
    snap.obligations = {o.obligation_id: o for o in (justified, stale)}
    graph = build_proof_graph(ot, pid, snap)
    flagged = [i for i in graph.issues if i.code == "unsupported_transition"]
    assert [i.node_ids for i in flagged] == [["OBL-0002"]]
    assert graph.nodes["OBL-0002"].extra["closure_audit"] == "unjustified"
    assert graph.nodes["OBL-0001"].extra["closure_audit"] == "justified"
