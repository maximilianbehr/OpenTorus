"""Portfolio helpers (M3: bootstrap + the dedup/activation pieces M4 builds on) and
the M3 scheduler semantics."""

from __future__ import annotations

from datetime import UTC, datetime

from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignSnapshot,
    RootRelation,
    WorkerRole,
)
from opentorus.campaign.phases import DossierFacts
from opentorus.campaign.portfolio import (
    activate_initial,
    bootstrap_portfolio,
    dedup_proposals,
    jaccard,
    normalize_objective,
)
from opentorus.campaign.scheduler import select_next
from opentorus.config import SchedulerWeights


def _snapshot() -> CampaignSnapshot:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    return CampaignSnapshot(
        campaign_id="CAMPAIGN-0001",
        problem_id="PROBLEM-0001",
        mode=CampaignMode.exploration,
        created_at=ts,
        updated_at=ts,
        counters={"BRANCH": 2},
    )


def _branch(
    bid: str, objective: str, *, kind: BranchKind = BranchKind.proof, priority: float = 1.0
) -> BranchRecord:
    return BranchRecord(
        branch_id=bid,
        campaign_id="CAMPAIGN-0001",
        title=bid,
        kind=kind,
        objective=objective,
        root_relation=RootRelation.equivalent,
        priority=priority,
        assigned_worker_role=WorkerRole.prover,
    )


def test_bootstrap_portfolio_is_one_literature_branch_from_the_counter() -> None:
    snap = _snapshot()
    snap.insufficient_categories = ["definitions_notation", "known_counterexamples"]
    branches = bootstrap_portfolio(
        snap, mode=CampaignMode.survey, coverage=snap.insufficient_categories
    )
    assert len(branches) == 1
    b = branches[0]
    assert b.branch_id == "BRANCH-0003"  # counter says two exist already
    assert b.kind is BranchKind.literature and b.root_relation is RootRelation.supporting
    assert b.assigned_worker_role is WorkerRole.librarian
    assert b.status is BranchStatus.proposed and b.priority == 1.0
    assert "PROBLEM-0001" in b.objective and "known_counterexamples" in b.objective
    assert b.strategy_key == "literature_map"
    # deterministic: same input, same proposal
    assert (
        bootstrap_portfolio(snap, mode=CampaignMode.survey, coverage=snap.insufficient_categories)
        == branches
    )


def test_dedup_rejects_near_duplicate_objectives_of_the_same_kind_and_relation() -> None:
    a = _branch("BRANCH-0001", "prove the bound by induction on n")
    b = _branch("BRANCH-0002", "prove the bound by induction on n (again)")
    c = _branch(
        "BRANCH-0003", "search for a counterexample numerically", kind=BranchKind.counterexample
    )
    d = _branch("BRANCH-0004", "prove the bound by induction on n", kind=BranchKind.special_case)
    result = dedup_proposals([a, b, c, d])
    assert [x.branch_id for x in result.accepted] == ["BRANCH-0001", "BRANCH-0003", "BRANCH-0004"]
    assert [x.branch_id for x in result.rejected] == ["BRANCH-0002"]
    rejected = result.rejected[0]
    assert rejected.status is BranchStatus.rejected
    assert rejected.rejection_reason == "REPEATED_STRATEGY"
    assert rejected.duplicate_of == "BRANCH-0001"
    assert jaccard(normalize_objective("a b c"), normalize_objective("a b c d")) == 0.75


def test_activate_initial_takes_top_priority_then_lowest_id() -> None:
    branches = [
        _branch("BRANCH-0003", "x", priority=0.8),
        _branch("BRANCH-0001", "y", priority=0.9),
        _branch("BRANCH-0002", "z", priority=0.9),
    ]
    assert [b.branch_id for b in activate_initial(branches, max_active=2)] == [
        "BRANCH-0001",
        "BRANCH-0002",
    ]
    assert activate_initial(branches, max_active=0) == []


def test_select_next_prefers_fewest_work_items_then_literature_then_id() -> None:
    snap = _snapshot()
    snap.budget.steps_limit = 10
    for bid, kind, items in (
        ("BRANCH-0001", BranchKind.proof, ["WI-0001"]),
        ("BRANCH-0002", BranchKind.literature, []),
        ("BRANCH-0003", BranchKind.counterexample, []),
    ):
        b = _branch(bid, f"objective {bid}", kind=kind)
        b.status = BranchStatus.active
        b.work_item_ids = list(items)
        snap.branches[bid] = b
    facts = DossierFacts(insufficient_categories=("definitions_notation",))
    plan = select_next(
        snap, SchedulerWeights(), CampaignMode.exploration, facts, branch_step_budget=10
    )
    assert plan is not None
    assert plan.branch_id == "BRANCH-0002"  # zero items and coverage insufficient
    assert plan.score.literature_boost == 1.0 and plan.score.tie_break == "BRANCH-0002"
    plan2 = select_next(
        snap, SchedulerWeights(), CampaignMode.exploration, DossierFacts(), branch_step_budget=10
    )
    assert (
        plan2 is not None and plan2.branch_id == "BRANCH-0002"
    )  # zero items, lowest id among ties
    snap.branches["BRANCH-0002"].work_item_ids = ["WI-0002"]
    plan3 = select_next(
        snap, SchedulerWeights(), CampaignMode.exploration, DossierFacts(), branch_step_budget=10
    )
    assert plan3 is not None and plan3.branch_id == "BRANCH-0003"
    # suspended / non-active branches are never scheduled; exhausted budgets end scheduling
    for b in snap.branches.values():
        b.status = BranchStatus.suspended
    assert select_next(snap, SchedulerWeights(), CampaignMode.exploration, DossierFacts()) is None
    snap.branches["BRANCH-0003"].status = BranchStatus.active
    snap.budget.steps_used = 10
    assert select_next(snap, SchedulerWeights(), CampaignMode.exploration, DossierFacts()) is None
    snap.budget.steps_used = 4
    plan4 = select_next(
        snap, SchedulerWeights(), CampaignMode.exploration, DossierFacts(), branch_step_budget=10
    )
    assert plan4 is not None and plan4.max_steps == 6  # min(branch remaining, campaign remaining)
