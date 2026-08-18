"""Portfolio helpers: the bootstrap, the dedup/cap/activation pipeline, the template
portfolio, and the scored scheduler's selection semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignSnapshot,
    NormalizedProblem,
    RootRelation,
    WorkerRole,
)
from opentorus.campaign.phases import DossierFacts, mode_profile
from opentorus.campaign.portfolio import (
    KIND_TO_ROLE,
    PORTFOLIO_SLACK,
    PortfolioContext,
    activate_initial,
    bootstrap_portfolio,
    cap_proposals,
    dedup_proposals,
    generate_portfolio,
    initial_priority,
    jaccard,
    mandatory_branches,
    normalize_objective,
    proposals_from_items,
    template_portfolio,
)
from opentorus.campaign.scheduler import select_next
from opentorus.campaign.workers.strategist import parse_strategist_json
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


def test_select_next_prefers_literature_boost_then_documented_factors() -> None:
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
    # Without the literature boost the documented factors decide: both zero-item branches
    # share fairness/novelty/root_impact (the helper gives every branch ``equivalent``), and
    # the exploration resolve_chance table ranks counterexample (0.6) above literature (0.5).
    assert plan2 is not None and plan2.branch_id == "BRANCH-0003"
    assert plan2.score.resolve_chance == 0.6 and plan2.score.fairness == 1.0
    snap.branches["BRANCH-0003"].work_item_ids = ["WI-0002"]
    plan3 = select_next(
        snap, SchedulerWeights(), CampaignMode.exploration, DossierFacts(), branch_step_budget=10
    )
    assert plan3 is not None and plan3.branch_id == "BRANCH-0002"  # now the least-worked one
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


# --------------------------------------------------------------------------------------
# M4: the template portfolio and the generate_portfolio pipeline
# --------------------------------------------------------------------------------------


def _problem() -> NormalizedProblem:
    return NormalizedProblem(
        problem_id="PROBLEM-0001",
        statement="For every n >= 1, P(n) holds.",
        assumptions=["n is a positive integer"],
    )


def _ctx(mode: CampaignMode, **overrides: object) -> PortfolioContext:
    base: dict[str, object] = {
        "campaign_id": "CAMPAIGN-0001",
        "mode": mode,
        "problem": _problem(),
        "coverage_insufficient": ("definitions_notation",),
        "critical_categories": tuple(mode_profile(mode).critical_coverage),
        "initial_branches": 4,
        "max_active_branches": 3,
    }
    base.update(overrides)
    return PortfolioContext(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", list(CampaignMode))
def test_template_portfolio_has_at_least_three_distinct_branches_per_mode(
    mode: CampaignMode,
) -> None:
    ctx = _ctx(mode)
    branches = template_portfolio(
        mode,
        4 + PORTFOLIO_SLACK,
        problem=ctx.problem,
        coverage=ctx.coverage_insufficient,
        critical=ctx.critical_categories,
        campaign_id="CAMPAIGN-0001",
    )
    assert len(branches) >= 3
    assert len({b.branch_id for b in branches}) == len(branches)
    assert len({(b.kind, b.objective) for b in branches}) == len(branches)
    # fixed order, priority 1.0 - 0.1*index, ids from the counter, roles by kind
    assert [b.priority for b in branches] == [initial_priority(i) for i in range(len(branches))]
    assert [b.branch_id for b in branches] == [
        f"BRANCH-{i:04d}" for i in range(1, len(branches) + 1)
    ]
    for b in branches:
        assert b.assigned_worker_role is KIND_TO_ROLE[b.kind]
        assert b.status is BranchStatus.proposed
        assert b.assumption_context == ["n is a positive integer"]
    assert dedup_proposals(branches).rejected == []  # the recipe never duplicates itself
    # deterministic: two calls are identical
    again = template_portfolio(
        mode,
        4 + PORTFOLIO_SLACK,
        problem=ctx.problem,
        coverage=ctx.coverage_insufficient,
        critical=ctx.critical_categories,
        campaign_id="CAMPAIGN-0001",
    )
    assert again == branches


def test_prove_or_refute_template_follows_the_documented_recipe() -> None:
    ctx = _ctx(CampaignMode.prove_or_refute)
    branches = template_portfolio(
        CampaignMode.prove_or_refute, 7, problem=ctx.problem, coverage=ctx.coverage_insufficient
    )
    assert [(b.strategy_key, b.kind, b.root_relation) for b in branches] == [
        ("proof_sketch", BranchKind.proof, RootRelation.equivalent),
        ("counterexample_search", BranchKind.counterexample, RootRelation.counterexample_route),
        ("literature_map", BranchKind.literature, RootRelation.supporting),
        ("formalization_attempt", BranchKind.formalization, RootRelation.equivalent),
        ("special_cases", BranchKind.special_case, RootRelation.special_case),
        ("obstruction_search", BranchKind.obstruction, RootRelation.supporting),
        ("symbolic_simplification", BranchKind.symbolic, RootRelation.supporting),
    ]
    special = branches[4]
    assert special.parent_branch_id == branches[0].branch_id  # parent = the proof branch
    from opentorus.research.dossier.strategies import STRATEGY_TEMPLATES

    assert STRATEGY_TEMPLATES["proof_sketch"].objective in branches[0].objective
    assert "definitions_notation" in branches[2].objective  # insufficient coverage named
    # exploration: numerical, counterexample, literature, special-case
    expl = template_portfolio(CampaignMode.exploration, 7, problem=ctx.problem)
    assert [b.kind for b in expl] == [
        BranchKind.numerical,
        BranchKind.counterexample,
        BranchKind.literature,
        BranchKind.special_case,
    ]
    # survey: one literature branch per critical category (capped) + one synthesis
    survey_ctx = _ctx(CampaignMode.survey)
    survey = template_portfolio(
        CampaignMode.survey,
        7,
        problem=ctx.problem,
        critical=survey_ctx.critical_categories,
        coverage=survey_ctx.critical_categories,
    )
    assert [b.kind for b in survey[:-1]] == [BranchKind.literature] * 6
    assert survey[-1].kind is BranchKind.synthesis
    assert dedup_proposals(survey).rejected == []  # per-category objectives are distinct


def test_generate_portfolio_prove_or_refute_caps_and_activates_proof_and_counterexample() -> None:
    proposal = generate_portfolio(None, _ctx(CampaignMode.prove_or_refute))
    assert proposal.source == "template"
    assert len(proposal.proposals) == 7
    assert [b.kind for b in proposal.accepted] == [
        BranchKind.proof,
        BranchKind.counterexample,
        BranchKind.literature,
        BranchKind.formalization,
    ]
    assert [b.rejection_reason for b in proposal.rejected] == ["PORTFOLIO_CAP"] * 3
    assert {b.kind for b in proposal.rejected} == {
        BranchKind.special_case,
        BranchKind.obstruction,
        BranchKind.symbolic,
    }
    assert all(b.status is BranchStatus.rejected for b in proposal.rejected)  # preserved
    activated_kinds = [b.kind for b in proposal.activated]
    assert BranchKind.proof in activated_kinds and BranchKind.counterexample in activated_kinds
    assert BranchKind.literature in activated_kinds  # forced: coverage insufficient
    assert len(proposal.activated) == 3
    queued = [b for b in proposal.accepted if b not in proposal.activated]
    assert [b.kind for b in queued] == [BranchKind.formalization]  # queued as proposed
    assert all(b.distinctness_note for b in proposal.accepted)
    # two calls are identical
    assert generate_portfolio(None, _ctx(CampaignMode.prove_or_refute)) == proposal


def test_generate_portfolio_rejects_duplicates_and_keeps_them() -> None:
    ctx = _ctx(CampaignMode.exploration, coverage_insufficient=())
    items = [
        {
            "title": "Numerics",
            "kind": "numerical",
            "objective": "compute P(n) for n up to a million and tabulate the ratios",
            "root_relation": "supporting",
        },
        {
            "title": "Numerics again",
            "kind": "numerical",
            "objective": "compute P(n) for n up to a million and tabulate the ratios again",
            "root_relation": "supporting",
        },
        {
            "title": "Search",
            "kind": "counterexample",
            "objective": "search n <= 10^6 for a failure of P(n)",
            "root_relation": "counterexample-route",
            "why_distinct": "refutation route",
        },
    ]
    proposals, notes = proposals_from_items(items, ctx, start_index=1)
    assert len(proposals) == 3 and notes == []
    result = dedup_proposals(proposals)
    assert [b.branch_id for b in result.accepted] == ["BRANCH-0001", "BRANCH-0003"]
    assert [b.branch_id for b in result.rejected] == ["BRANCH-0002"]
    dup = result.rejected[0]
    assert dup.rejection_reason == "REPEATED_STRATEGY" and dup.duplicate_of == "BRANCH-0001"
    assert dup.status is BranchStatus.rejected  # preserved, not discarded
    assert result.accepted[1].distinctness_note == "refutation route"


def test_cap_keeps_mandatory_branches_and_activation_swaps_them_in() -> None:
    ctx = _ctx(CampaignMode.prove_or_refute)
    branches = template_portfolio(
        CampaignMode.prove_or_refute, 7, problem=ctx.problem, coverage=ctx.coverage_insufficient
    )
    # push the proof branch to the end with the lowest priority: the cap must still keep it
    reordered = branches[1:] + branches[:1]
    for i, b in enumerate(reordered):
        b.priority = initial_priority(i)
    capped = cap_proposals(
        reordered, initial_branches=2, mode=CampaignMode.prove_or_refute, coverage_insufficient=()
    )
    kinds = {b.kind for b in capped.accepted}
    assert BranchKind.proof in kinds and BranchKind.counterexample in kinds
    assert len(capped.accepted) == 2
    assert all(b.rejection_reason == "PORTFOLIO_CAP" for b in capped.rejected)
    # activation with max_active=1 still activates both mandatory routes (documented)
    activated = activate_initial(capped.accepted, max_active=1, mode=CampaignMode.prove_or_refute)
    assert {b.kind for b in activated} == {BranchKind.proof, BranchKind.counterexample}
    # literature is forced only while coverage is insufficient
    assert [b.kind for b in mandatory_branches(branches, mode="exploration")] == []
    assert [
        b.kind
        for b in mandatory_branches(branches, mode="exploration", coverage_insufficient=("x",))
    ] == [BranchKind.literature]
    survey = generate_portfolio(None, _ctx(CampaignMode.survey, initial_branches=3))
    assert len(survey.accepted) == 3
    assert survey.accepted[0].kind is BranchKind.literature
    assert any(b.kind is BranchKind.literature for b in survey.activated)


def test_parse_strategist_json_is_lenient() -> None:
    text = 'Sure! Here you go:\n```json\n[{"title": "A", "kind": "proof", "objective": "x"}]\n```'
    assert parse_strategist_json(text) == [{"title": "A", "kind": "proof", "objective": "x"}]
    assert parse_strategist_json("no json here") == []
    assert parse_strategist_json('{"not": "a list"}') == []
    assert parse_strategist_json('[1, 2, {"kind": "proof", "objective": "y"}]') == [
        {"kind": "proof", "objective": "y"}
    ]
    ctx = _ctx(CampaignMode.prove_or_refute)
    proposals, notes = proposals_from_items(
        [{"title": "?", "kind": "nonsense", "objective": "z"}, {"kind": "proof", "objective": ""}],
        ctx,
        start_index=1,
    )
    assert proposals == [] and len(notes) == 2
