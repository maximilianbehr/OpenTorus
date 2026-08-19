"""The campaign phase table and mode profiles."""

from __future__ import annotations

import pytest

from opentorus.agent.control.phase_machine import InvalidTransition
from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignSnapshot,
    RootRelation,
)
from opentorus.campaign.models import (
    CampaignPhase as P,
)
from opentorus.campaign.phases import (
    CAMPAIGN_MACHINE,
    PHASE_TRANSITIONS,
    TERMINAL_PHASES,
    DossierFacts,
    allowed_targets,
    assert_transition,
    can_transition,
    is_terminal,
    mode_profile,
)

ALLOWED = [
    (P.CREATED, P.INGEST),
    (P.INGEST, P.NORMALIZE),
    (P.NORMALIZE, P.MAP_LITERATURE),
    (P.MAP_LITERATURE, P.GENERATE_PORTFOLIO),
    (P.GENERATE_PORTFOLIO, P.SCHEDULE),
    (P.SCHEDULE, P.EXECUTE),
    (P.SCHEDULE, P.SYNTHESIZE),
    (P.EXECUTE, P.CRITIQUE),
    (P.CRITIQUE, P.VERIFY),
    (P.VERIFY, P.UPDATE_GRAPH),
    (P.UPDATE_GRAPH, P.REALLOCATE),
    (P.REALLOCATE, P.SCHEDULE),
    (P.REALLOCATE, P.SYNTHESIZE),
    (P.SYNTHESIZE, P.COMPLETED),
    (P.PAUSED, P.STOPPED),
]

FORBIDDEN = [
    (P.CREATED, P.SCHEDULE),
    (P.INGEST, P.EXECUTE),
    (P.SCHEDULE, P.CRITIQUE),
    (P.EXECUTE, P.SCHEDULE),
    (P.CRITIQUE, P.EXECUTE),
    (P.VERIFY, P.SCHEDULE),
    (P.REALLOCATE, P.EXECUTE),
    (P.SYNTHESIZE, P.SCHEDULE),
    (P.COMPLETED, P.INGEST),
    (P.STOPPED, P.SCHEDULE),
    (P.FAILED, P.INGEST),
    (P.PAUSED, P.INGEST),  # no resume_phase stored -> not allowed
    (P.PAUSED, P.COMPLETED),
    (P.COMPLETED, P.PAUSED),
]


@pytest.mark.parametrize(("src", "dst"), ALLOWED)
def test_allowed_transitions(src: P, dst: P) -> None:
    assert can_transition(src, dst)
    assert_transition(src, dst)


@pytest.mark.parametrize(("src", "dst"), FORBIDDEN)
def test_forbidden_transitions_raise(src: P, dst: P) -> None:
    assert not can_transition(src, dst)
    with pytest.raises(InvalidTransition):
        assert_transition(src, dst)


def test_every_non_terminal_can_pause_stop_fail() -> None:
    for phase in P:
        if phase in TERMINAL_PHASES or phase is P.PAUSED:
            continue
        for hold in (P.PAUSED, P.STOPPED, P.FAILED):
            assert can_transition(phase, hold), (phase, hold)


def test_paused_returns_only_to_its_stored_resume_phase() -> None:
    assert can_transition(P.PAUSED, P.SCHEDULE, resume_phase=P.SCHEDULE)
    assert not can_transition(P.PAUSED, P.EXECUTE, resume_phase=P.SCHEDULE)
    assert allowed_targets(P.PAUSED, resume_phase=P.REALLOCATE) == {P.STOPPED, P.REALLOCATE}
    # a terminal resume phase never re-opens a paused campaign
    assert allowed_targets(P.PAUSED, resume_phase=P.COMPLETED) == {P.STOPPED}


def test_terminal_phases_are_terminal_and_idempotent() -> None:
    assert TERMINAL_PHASES == {P.COMPLETED, P.STOPPED, P.FAILED}
    for phase in TERMINAL_PHASES:
        assert is_terminal(phase)
        assert CAMPAIGN_MACHINE.is_terminal(phase)
        assert allowed_targets(phase) == frozenset()
        assert phase not in PHASE_TRANSITIONS


def test_machine_table_matches_module_table() -> None:
    assert dict(CAMPAIGN_MACHINE.transitions) == PHASE_TRANSITIONS


def _snapshot(*branches: BranchStatus, exhausted: list[str] | None = None) -> CampaignSnapshot:
    from datetime import UTC, datetime

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    snap = CampaignSnapshot(
        campaign_id="CAMPAIGN-0001",
        problem_id="PROBLEM-0001",
        mode=CampaignMode.exploration,
        created_at=ts,
        updated_at=ts,
    )
    for i, status in enumerate(branches, start=1):
        bid = f"BRANCH-{i:04d}"
        snap.branches[bid] = BranchRecord(
            branch_id=bid,
            campaign_id="CAMPAIGN-0001",
            title="t",
            kind=BranchKind.literature,
            objective="o",
            root_relation=RootRelation.supporting,
            status=status,
        )
    snap.budget.exhausted = list(exhausted or [])
    return snap


def test_prove_or_refute_completion_rules() -> None:
    profile = mode_profile(CampaignMode.prove_or_refute)
    facts = DossierFacts(root_label="INCONCLUSIVE")
    assert not profile.completion(_snapshot(BranchStatus.active), facts).complete
    assert profile.completion(_snapshot(BranchStatus.completed), facts).criterion == "no_branches"
    assert (
        profile.completion(_snapshot(BranchStatus.active, exhausted=["steps"]), facts).criterion
        == "budget"
    )
    settled = DossierFacts(root_label="GENERAL_CONJECTURE_REFUTED")
    assert profile.completion(_snapshot(BranchStatus.active), settled).criterion == "root_settled"


def test_exploration_and_survey_completion_rules() -> None:
    exploration = mode_profile("exploration")
    facts = DossierFacts()
    assert not exploration.completion(_snapshot(BranchStatus.proposed), facts).complete
    assert (
        exploration.completion(_snapshot(BranchStatus.exhausted), facts).criterion == "no_branches"
    )
    survey = mode_profile(CampaignMode.survey)
    snap = _snapshot(BranchStatus.active)
    snap.coverage_ref = "COV-0001"
    assert survey.completion(snap, DossierFacts(insufficient_categories=())).criterion == "coverage"
    assert not survey.completion(snap, DossierFacts(insufficient_categories=("x",))).complete


def test_portfolio_recipes_and_critical_coverage() -> None:
    por = mode_profile(CampaignMode.prove_or_refute)
    keys = [k for k, _kind, _rel in por.portfolio_recipe]
    assert keys == [
        "proof_sketch",
        "counterexample_search",
        "literature_map",
        "formalization_attempt",
        "special_cases",
        "obstruction_search",
        "symbolic_simplification",
    ]
    assert por.portfolio_recipe[0][1:] == (BranchKind.proof, RootRelation.equivalent)
    assert por.portfolio_recipe[1][1:] == (
        BranchKind.counterexample,
        RootRelation.counterexample_route,
    )
    assert [k for k, *_ in mode_profile("exploration").portfolio_recipe] == [
        "numerical_experiment",
        "counterexample_search",
        "literature_map",
        "special_cases",
    ]
    assert len(mode_profile("survey").critical_coverage) == 11
    assert "original_problem_source" in por.critical_coverage
