"""The scored scheduler: documented factors, tie-breaks, spread, suspension and
reactivation — on synthetic snapshots and on a real engine run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignSnapshot,
    CampaignStatus,
    ClosureMode,
    FailureSignature,
    Obligation,
    ObligationStatus,
    ReactivationCondition,
    RootRelation,
    WorkerRole,
    WorkItem,
    WorkItemStatus,
)
from opentorus.campaign.phases import DossierFacts
from opentorus.campaign.scheduler import (
    RESOLVE_CHANCE,
    ROOT_IMPACT,
    identical_failure_streak,
    reactivation_due,
    score_branch,
    select_next,
)
from opentorus.campaign.store import open_campaign
from opentorus.config import SchedulerWeights
from support.campaign import make_engine, make_workspace

TS = datetime(2026, 1, 1, tzinfo=UTC)


def _snapshot(**overrides: object) -> CampaignSnapshot:
    base: dict[str, object] = {
        "campaign_id": "CAMPAIGN-0001",
        "problem_id": "PROBLEM-0001",
        "mode": CampaignMode.prove_or_refute,
        "created_at": TS,
        "updated_at": TS,
    }
    base.update(overrides)
    snap = CampaignSnapshot(**base)  # type: ignore[arg-type]
    snap.budget.steps_limit = 100
    return snap


def _branch(
    bid: str,
    kind: BranchKind,
    relation: RootRelation,
    *,
    objective: str | None = None,
    status: BranchStatus = BranchStatus.active,
    dependencies: list[str] | None = None,
) -> BranchRecord:
    return BranchRecord(
        branch_id=bid,
        campaign_id="CAMPAIGN-0001",
        title=bid,
        kind=kind,
        objective=objective or f"objective of {bid} {kind.value}",
        root_relation=relation,
        status=status,
        assigned_worker_role=WorkerRole.prover,
        estimated_cost=1.0,
        dependencies=list(dependencies or []),
    )


def _item(wid: str, bid: str, status: WorkItemStatus, sig: str | None = None) -> WorkItem:
    return WorkItem(
        work_item_id=wid,
        campaign_id="CAMPAIGN-0001",
        branch_id=bid,
        role=WorkerRole.prover,
        task_class="proof_development",
        objective="x",
        status=status,
        failure_signature_id=sig,
    )


def test_score_breakdown_reports_the_documented_factors() -> None:
    snap = _snapshot()
    proof = _branch("BRANCH-0001", BranchKind.proof, RootRelation.equivalent)
    ce = _branch("BRANCH-0002", BranchKind.counterexample, RootRelation.counterexample_route)
    ce.dependencies = ["BRANCH-0001"]
    snap.branches = {b.branch_id: b for b in (proof, ce)}
    weights = SchedulerWeights()
    score = score_branch(proof, snap, weights, CampaignMode.prove_or_refute, DossierFacts())
    assert score.root_impact == ROOT_IMPACT[RootRelation.equivalent] == 1.0
    assert score.info_gain == 1.0  # no completed items yet
    assert score.resolve_chance == RESOLVE_CHANCE[CampaignMode.prove_or_refute][BranchKind.proof]
    assert score.verifier_readiness == 0.0
    assert score.novelty == 1.0
    assert score.dependency_criticality == 1.5  # one branch depends on it
    assert score.cost == 0.0  # branch budget unlimited → no cost
    assert score.redundancy < 0.8
    assert score.failure_risk == 0.0
    assert score.fairness == 1.0 and score.literature_boost == 0.0
    expected = (
        weights.root_impact * (1.0 + 1.0 + 0.6) / 3
        + weights.novelty * 1.0
        + weights.dependency * 1.5
        + 1.0
        - weights.redundancy * score.redundancy
    )
    assert score.total == pytest.approx(expected, abs=1e-6)
    assert score.tie_break == "BRANCH-0001"
    # cost is estimated_cost / branch_step_budget when a branch budget exists
    with_cost = score_branch(
        proof, snap, weights, CampaignMode.prove_or_refute, DossierFacts(), branch_step_budget=10
    )
    assert with_cost.cost == pytest.approx(0.1)
    # literature boost while coverage is insufficient
    lit = _branch("BRANCH-0003", BranchKind.literature, RootRelation.supporting)
    snap.branches[lit.branch_id] = lit
    boosted = score_branch(
        lit,
        snap,
        weights,
        CampaignMode.prove_or_refute,
        DossierFacts(insufficient_categories=("definitions_notation",)),
    )
    assert boosted.literature_boost == 1.0
    assert (
        score_branch(lit, snap, weights, CampaignMode.survey, DossierFacts()).literature_boost
        == 1.0
    )
    assert (
        score_branch(lit, snap, weights, CampaignMode.exploration, DossierFacts()).literature_boost
        == 0.0
    )


def test_ties_break_by_branch_id() -> None:
    snap = _snapshot()
    for bid in ("BRANCH-0002", "BRANCH-0001", "BRANCH-0003"):
        snap.branches[bid] = _branch(bid, BranchKind.proof, RootRelation.equivalent, objective=bid)
    plan = select_next(snap, SchedulerWeights(), CampaignMode.prove_or_refute, DossierFacts())
    assert plan is not None and plan.branch_id == "BRANCH-0001"


def test_first_three_work_items_span_three_distinct_branches(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="prove-or-refute", branches=4, max_steps=40)
    snap = open_campaign(ot, record.id).load().snapshot
    first_three = sorted(snap.work_items.values(), key=lambda wi: wi.work_item_id)[:3]
    assert len({wi.branch_id for wi in first_three}) == 3  # a set assertion, not an order


def test_repeated_failure_lowers_the_score_and_verifier_readiness_raises_it() -> None:
    snap = _snapshot()
    a = _branch("BRANCH-0001", BranchKind.proof, RootRelation.equivalent, objective="a a a")
    b = _branch("BRANCH-0002", BranchKind.proof, RootRelation.equivalent, objective="b b b")
    snap.branches = {a.branch_id: a, b.branch_id: b}
    weights = SchedulerWeights()
    facts = DossierFacts()
    base_a = score_branch(a, snap, weights, CampaignMode.prove_or_refute, facts).total
    a.consecutive_failures = 2
    assert score_branch(a, snap, weights, CampaignMode.prove_or_refute, facts).failure_risk == (
        pytest.approx(2 / 3)
    )
    assert score_branch(a, snap, weights, CampaignMode.prove_or_refute, facts).total < base_a
    a.consecutive_failures = 0
    # a gap-free proof awaiting verification raises the branch's score
    snap.obligations["OBL-0001"] = Obligation(
        obligation_id="OBL-0001",
        campaign_id="CAMPAIGN-0001",
        branch_id="BRANCH-0002",
        statement="whole proof",
        source_proof_id="PROOF-0001",
        gap_marker=None,
        closure_modes=[ClosureMode.nl_proof_referee_accepted],
    )
    ready = score_branch(b, snap, weights, CampaignMode.prove_or_refute, facts)
    assert ready.verifier_readiness == 1.0
    assert ready.total > score_branch(a, snap, weights, CampaignMode.prove_or_refute, facts).total
    snap.obligations["OBL-0001"].status = ObligationStatus.closed
    assert (
        score_branch(b, snap, weights, CampaignMode.prove_or_refute, facts).verifier_readiness
        == 0.0
    )


def test_duplicates_are_penalised_and_novelty_decays() -> None:
    snap = _snapshot()
    a = _branch(
        "BRANCH-0001",
        BranchKind.proof,
        RootRelation.equivalent,
        objective="prove it by induction on n",
    )
    b = _branch(
        "BRANCH-0002",
        BranchKind.symbolic,
        RootRelation.supporting,
        objective="prove it by induction on n now",
    )
    c = _branch(
        "BRANCH-0003",
        BranchKind.counterexample,
        RootRelation.counterexample_route,
        objective="search small cases",
    )
    snap.branches = {x.branch_id: x for x in (a, b, c)}
    weights = SchedulerWeights()
    facts = DossierFacts()
    dup = score_branch(b, snap, weights, CampaignMode.exploration, facts)
    assert dup.redundancy >= 0.8
    b.objective = "sympy rewrite of the recurrence"
    assert score_branch(b, snap, weights, CampaignMode.exploration, facts).redundancy < 0.8
    # novelty decays 0.5 ** items; fairness drops once a branch has more items than the
    # least-worked active branch
    a.work_item_ids = ["WI-0001", "WI-0002"]
    scored = score_branch(a, snap, weights, CampaignMode.exploration, facts)
    assert scored.novelty == 0.25 and scored.fairness == 0.0
    plan = select_next(snap, weights, CampaignMode.exploration, facts)
    assert plan is not None and plan.branch_id != "BRANCH-0001"


def test_suspended_and_blocked_branches_are_not_scheduled() -> None:
    snap = _snapshot()
    a = _branch(
        "BRANCH-0001", BranchKind.proof, RootRelation.equivalent, status=BranchStatus.suspended
    )
    b = _branch(
        "BRANCH-0002",
        BranchKind.formalization,
        RootRelation.equivalent,
        dependencies=["BRANCH-0001"],
    )
    snap.branches = {a.branch_id: a, b.branch_id: b}
    # b depends on a suspended (not completed) branch → nothing runnable
    assert (
        select_next(snap, SchedulerWeights(), CampaignMode.prove_or_refute, DossierFacts()) is None
    )
    a.status = BranchStatus.completed
    plan = select_next(snap, SchedulerWeights(), CampaignMode.prove_or_refute, DossierFacts())
    assert plan is not None and plan.branch_id == "BRANCH-0002"
    # an excluded branch (refused retry this round) is skipped
    assert (
        select_next(
            snap,
            SchedulerWeights(),
            CampaignMode.prove_or_refute,
            DossierFacts(),
            exclude={"BRANCH-0002"},
        )
        is None
    )


def test_identical_failure_streak_counts_trailing_same_key_failures() -> None:
    snap = _snapshot()
    a = _branch("BRANCH-0001", BranchKind.proof, RootRelation.equivalent)
    snap.branches[a.branch_id] = a
    snap.failure_signatures = {
        "FSIG-0001": FailureSignature(signature_id="FSIG-0001", key="k1", strategy_class="p"),
        "FSIG-0002": FailureSignature(signature_id="FSIG-0002", key="k2", strategy_class="p"),
    }
    snap.work_items = {
        "WI-0001": _item("WI-0001", a.branch_id, WorkItemStatus.completed),
        "WI-0002": _item("WI-0002", a.branch_id, WorkItemStatus.failed, "FSIG-0001"),
        "WI-0003": _item("WI-0003", a.branch_id, WorkItemStatus.failed, "FSIG-0001"),
    }
    a.work_item_ids = ["WI-0001", "WI-0002", "WI-0003"]
    assert identical_failure_streak(a, snap) == (2, "k1")
    snap.work_items["WI-0004"] = _item("WI-0004", a.branch_id, WorkItemStatus.failed, "FSIG-0002")
    a.work_item_ids.append("WI-0004")
    assert identical_failure_streak(a, snap) == (1, "k2")
    snap.work_items["WI-0005"] = _item("WI-0005", a.branch_id, WorkItemStatus.failed, None)
    a.work_item_ids.append("WI-0005")
    assert identical_failure_streak(a, snap) == (0, None)


def test_reactivation_only_when_the_recorded_condition_is_met() -> None:
    snap = _snapshot()
    a = _branch(
        "BRANCH-0001",
        BranchKind.formalization,
        RootRelation.equivalent,
        status=BranchStatus.suspended,
    )
    a.reactivation_conditions = [
        ReactivationCondition(
            kind="verification_backend_changed", reference="", observed_at_suspension=0.0
        )
    ]
    b = _branch(
        "BRANCH-0002",
        BranchKind.counterexample,
        RootRelation.counterexample_route,
        status=BranchStatus.suspended,
    )
    b.reactivation_conditions = [
        ReactivationCondition(kind="new_evidence_count", threshold=3.0, observed_at_suspension=2.0)
    ]
    c = _branch(
        "BRANCH-0003", BranchKind.literature, RootRelation.supporting, status=BranchStatus.suspended
    )
    c.reactivation_conditions = [ReactivationCondition(kind="human_override")]
    snap.branches = {x.branch_id: x for x in (a, b, c)}
    unchanged = DossierFacts(evidence_count=2, verifier_backends=())
    assert reactivation_due(a, snap, unchanged) is None
    assert reactivation_due(b, snap, unchanged) is None
    assert reactivation_due(c, snap, unchanged) is None
    changed = DossierFacts(evidence_count=3, verifier_backends=("lean4",))
    assert reactivation_due(a, snap, changed) is not None
    assert reactivation_due(a, snap, changed).kind == "verification_backend_changed"  # type: ignore[union-attr]
    assert reactivation_due(b, snap, changed).kind == "new_evidence_count"  # type: ignore[union-attr]
    assert reactivation_due(c, snap, changed) is None  # never automatic
    d = _branch(
        "BRANCH-0004", BranchKind.proof, RootRelation.equivalent, status=BranchStatus.suspended
    )
    d.reactivation_conditions = [
        ReactivationCondition(kind="theorem_ref_accepted", threshold=1.0),
        ReactivationCondition(kind="branch_completed", reference="BRANCH-0003"),
    ]
    snap.branches[d.branch_id] = d
    assert reactivation_due(d, snap, DossierFacts()) is None
    assert (
        reactivation_due(d, snap, DossierFacts(accepted_theorem_ref_count=1)).kind
        == "theorem_ref_accepted"
    )  # type: ignore[union-attr]
    c.status = BranchStatus.completed
    assert reactivation_due(d, snap, DossierFacts()).kind == "branch_completed"  # type: ignore[union-attr]


def test_engine_reactivates_a_suspended_branch_when_the_backend_changes(tmp_path: Path) -> None:
    """The formalizer fails ``tool_unavailable`` (no lean/coq/smt), the retry is refused
    and the branch is suspended with ``verification_backend_changed``; a resume under a
    config that enables a formal backend reactivates it (and only then)."""
    from opentorus.config import default_config

    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="prove-or-refute", branches=4, max_steps=40, run=False)
    formal_bid: str | None = None

    def _until(snap: CampaignSnapshot) -> bool:
        nonlocal formal_bid
        for b in snap.branches.values():
            if b.kind is BranchKind.formalization and b.status is BranchStatus.suspended:
                formal_bid = b.branch_id
                return True
        return False

    engine.run(record.id, until=_until)
    assert formal_bid is not None
    store = open_campaign(ot, record.id)
    snap = store.load().snapshot
    branch = snap.branches[formal_bid]
    assert branch.suspension_reason == "REPEATED_IDENTICAL_FAILURE"
    assert [c.kind for c in branch.reactivation_conditions] == ["verification_backend_changed"]
    assert branch.reactivation_conditions[0].reference == "interval,sympy"  # what was enabled
    types = [e.type for e in store.read_events()[0]]
    assert "retry_refused" in types and "branch_suspended" in types
    assert "branch_reactivated" not in types
    engine.pause(record.id, "handover")
    # Same facts → resumed run finishes without reactivating anything.
    same = make_engine(root, ot)
    same.resume(record.id)
    types = [e.type for e in store.read_events()[0]]
    assert "branch_reactivated" not in types
    final = store.load().snapshot
    assert final.status is CampaignStatus.completed
    assert final.branches[formal_bid].status is BranchStatus.suspended
    # A fresh campaign under a config with a formal backend: the formalizer's failure is
    # a *different* signature (verifier_inconclusive), and a branch suspended for the
    # backend condition in another campaign would now be due — checked directly.
    config = default_config()
    config.tools.verifiers.smt = True
    facts_now = DossierFacts(verifier_backends=("interval", "smt", "sympy"))
    assert reactivation_due(final.branches[formal_bid], final, facts_now) is not None
    engine2 = make_engine(root, ot, config=config)
    second = engine2.start(pid, mode="prove-or-refute", branches=4, max_steps=40)
    snap2 = open_campaign(ot, second.id).load().snapshot
    formal2 = next(b for b in snap2.branches.values() if b.kind is BranchKind.formalization)
    sigs = [snap2.failure_signatures[s] for s in formal2.failure_signatures]
    assert [s.error_category for s in sigs] == ["verifier_inconclusive"]
    assert sigs[0].verifier_backends == ["smt"]


def test_budget_exhaustion_is_a_clean_pause_and_resume_completes(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="prove-or-refute", branches=4, max_steps=3)
    snap = open_campaign(ot, record.id).load().snapshot
    assert snap.status is CampaignStatus.paused
    assert snap.pause_reason == "BUDGET_EXHAUSTED"
    assert snap.budget.exhausted == ["steps"]
    assert open_campaign(ot, record.id).verify_replay().matches
    result = engine.resume(record.id)
    assert result.resumed
    final = open_campaign(ot, record.id).load().snapshot
    assert final.status is CampaignStatus.completed
    assert "budget exhausted" in (final.completion_reason or "")
