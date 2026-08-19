"""The campaign phase machine and the per-mode profiles.

The transition table is data, checked by the generic
:class:`~opentorus.agent.control.phase_machine.PhaseMachine` — at *append* time in
the store (an illegal transition raises :class:`InvalidTransition`, which the engine
turns into ``campaign_failed``) and at *replay* time in the reducer (an illegal
transition in an old log becomes a diagnostic and is skipped, so replay never
crashes). ``PAUSED`` is special: it may only return to the phase stored as
``resume_phase`` (or stop), so the resume rule needs the snapshot, not just the
table — see :func:`allowed_targets`.

A :class:`ModeProfile` says what a mode's portfolio recipe is, which literature
categories are critical, and when the campaign is *complete*. Completion is an
orchestration verdict ("nothing left to run / budget spent / root settled per the
dossier") — it never changes a claim status and never means the problem is solved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from opentorus.agent.control.phase_machine import InvalidTransition, PhaseMachine
from opentorus.campaign.models import (
    BranchKind,
    BranchStatus,
    CampaignMode,
    CampaignPhase,
    CampaignSnapshot,
    RootRelation,
)

P = CampaignPhase

TERMINAL_PHASES: frozenset[CampaignPhase] = frozenset({P.COMPLETED, P.STOPPED, P.FAILED})
WORKING_PHASES: tuple[CampaignPhase, ...] = (
    P.CREATED,
    P.INGEST,
    P.NORMALIZE,
    P.MAP_LITERATURE,
    P.GENERATE_PORTFOLIO,
    P.SCHEDULE,
    P.EXECUTE,
    P.CRITIQUE,
    P.VERIFY,
    P.UPDATE_GRAPH,
    P.REALLOCATE,
    P.SYNTHESIZE,
)
_HOLD: frozenset[CampaignPhase] = frozenset({P.PAUSED, P.STOPPED, P.FAILED})

PHASE_TRANSITIONS: dict[CampaignPhase, frozenset[CampaignPhase]] = {
    P.CREATED: frozenset({P.INGEST}) | _HOLD,
    P.INGEST: frozenset({P.NORMALIZE}) | _HOLD,
    P.NORMALIZE: frozenset({P.MAP_LITERATURE}) | _HOLD,
    P.MAP_LITERATURE: frozenset({P.GENERATE_PORTFOLIO}) | _HOLD,
    P.GENERATE_PORTFOLIO: frozenset({P.SCHEDULE}) | _HOLD,
    P.SCHEDULE: frozenset({P.EXECUTE, P.SYNTHESIZE}) | _HOLD,
    P.EXECUTE: frozenset({P.CRITIQUE}) | _HOLD,
    P.CRITIQUE: frozenset({P.VERIFY}) | _HOLD,
    P.VERIFY: frozenset({P.UPDATE_GRAPH}) | _HOLD,
    P.UPDATE_GRAPH: frozenset({P.REALLOCATE}) | _HOLD,
    P.REALLOCATE: frozenset({P.SCHEDULE, P.SYNTHESIZE}) | _HOLD,
    P.SYNTHESIZE: frozenset({P.COMPLETED}) | _HOLD,
    # PAUSED additionally returns to its stored resume_phase (see allowed_targets).
    P.PAUSED: frozenset({P.STOPPED}),
    # COMPLETED / STOPPED / FAILED: terminal — absent, so nothing leads out.
}

CAMPAIGN_MACHINE: PhaseMachine[CampaignPhase] = PhaseMachine(PHASE_TRANSITIONS)


def is_terminal(phase: CampaignPhase) -> bool:
    return phase in TERMINAL_PHASES


def allowed_targets(
    current: CampaignPhase, *, resume_phase: CampaignPhase | None = None
) -> frozenset[CampaignPhase]:
    """The phases ``current`` may move to, honouring the PAUSED → resume_phase rule."""
    allowed = CAMPAIGN_MACHINE.allowed(current)
    if current is P.PAUSED and resume_phase is not None and resume_phase not in TERMINAL_PHASES:
        allowed = allowed | {resume_phase}
    return allowed


def can_transition(
    current: CampaignPhase, target: CampaignPhase, *, resume_phase: CampaignPhase | None = None
) -> bool:
    return target in allowed_targets(current, resume_phase=resume_phase)


def assert_transition(
    current: CampaignPhase, target: CampaignPhase, *, resume_phase: CampaignPhase | None = None
) -> None:
    """Raise :class:`InvalidTransition` unless ``current -> target`` is allowed."""
    if not can_transition(current, target, resume_phase=resume_phase):
        raise InvalidTransition(
            current, target, allowed_targets(current, resume_phase=resume_phase)
        )


# --------------------------------------------------------------------------------------
# Mode profiles
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DossierFacts:
    """What the engine reads from the dossier for completion decisions (derived, read-only).

    ``root_label`` is ``scope.classify_outcome``'s label and ``report_status`` is
    ``status_gate.derive_status``'s — both computed from dossier artifacts, never from
    campaign state. ``insufficient_categories`` comes from the latest coverage assessment.
    """

    root_label: str = "STATUS_UNCERTAIN"
    root_rationale: str = ""
    report_status: str = "UNSOLVED"
    insufficient_categories: tuple[str, ...] = ()
    coverage_ref: str | None = None
    # Counts the scheduler's reactivation rules compare against (all derived, read-only):
    # evidence recorded for the problem (dossier ledger + workspace evidence attributed to
    # it or to a claim the campaign targets), theorem references a human accepted, and the
    # verifier backends enabled right now.
    evidence_count: int = 0
    accepted_theorem_ref_count: int = 0
    verifier_backends: tuple[str, ...] = ()


ROOT_SETTLED_LABELS: frozenset[str] = frozenset(
    {"GENERAL_CONJECTURE_PROVED", "GENERAL_CONJECTURE_REFUTED"}
)


@dataclass(frozen=True)
class CompletionVerdict:
    complete: bool
    reason: str
    criterion: str = ""


PortfolioRecipe = tuple[tuple[str, BranchKind, RootRelation], ...]

_PROVE_OR_REFUTE_RECIPE: PortfolioRecipe = (
    ("proof_sketch", BranchKind.proof, RootRelation.equivalent),
    ("counterexample_search", BranchKind.counterexample, RootRelation.counterexample_route),
    ("literature_map", BranchKind.literature, RootRelation.supporting),
    ("formalization_attempt", BranchKind.formalization, RootRelation.equivalent),
    ("special_cases", BranchKind.special_case, RootRelation.special_case),
    ("obstruction_search", BranchKind.obstruction, RootRelation.supporting),
    ("symbolic_simplification", BranchKind.symbolic, RootRelation.supporting),
)
_EXPLORATION_RECIPE: PortfolioRecipe = (
    ("numerical_experiment", BranchKind.numerical, RootRelation.supporting),
    ("counterexample_search", BranchKind.counterexample, RootRelation.counterexample_route),
    ("literature_map", BranchKind.literature, RootRelation.supporting),
    ("special_cases", BranchKind.special_case, RootRelation.special_case),
)
# Survey: one literature branch per critical coverage category (expanded by the
# portfolio module from ``critical_coverage``) plus a synthesis branch.
_SURVEY_RECIPE: PortfolioRecipe = (
    ("literature_map", BranchKind.literature, RootRelation.supporting),
    ("literature_map", BranchKind.synthesis, RootRelation.supporting),
)

RUNNABLE_BRANCH_STATUSES: frozenset[BranchStatus] = frozenset(
    {BranchStatus.active, BranchStatus.proposed}
)


def runnable_branches(snapshot: CampaignSnapshot) -> list[str]:
    """Branch ids that could still be scheduled (active now, or queued as proposed)."""
    return sorted(
        bid for bid, b in snapshot.branches.items() if b.status in RUNNABLE_BRANCH_STATUSES
    )


@dataclass(frozen=True)
class ModeProfile:
    """Per-mode policy: recipe, critical coverage, completion criterion."""

    mode: CampaignMode
    portfolio_recipe: PortfolioRecipe = field(default=())

    @property
    def critical_coverage(self) -> list[str]:
        from opentorus.research.theorems.coverage import critical_categories

        return [c.value for c in critical_categories(self.mode.value)]

    def completion(self, snapshot: CampaignSnapshot, facts: DossierFacts) -> CompletionVerdict:
        budget_spent = bool(snapshot.budget.exhausted)
        runnable = runnable_branches(snapshot)
        if self.mode is CampaignMode.prove_or_refute:
            if facts.root_label in ROOT_SETTLED_LABELS:
                return CompletionVerdict(
                    True,
                    f"root settled per dossier artifacts ({facts.root_label})",
                    "root_settled",
                )
            if not runnable:
                return CompletionVerdict(
                    True, "no active or proposed branches remain", "no_branches"
                )
            if budget_spent:
                return CompletionVerdict(
                    True, f"budget exhausted ({', '.join(snapshot.budget.exhausted)})", "budget"
                )
            return CompletionVerdict(False, f"{len(runnable)} runnable branch(es)")
        if self.mode is CampaignMode.exploration:
            if budget_spent:
                return CompletionVerdict(
                    True, f"budget exhausted ({', '.join(snapshot.budget.exhausted)})", "budget"
                )
            if not runnable:
                return CompletionVerdict(True, "no runnable branches remain", "no_branches")
            return CompletionVerdict(False, f"{len(runnable)} runnable branch(es)")
        # survey
        if snapshot.coverage_ref is not None and not facts.insufficient_categories:
            return CompletionVerdict(
                True, "no insufficient critical coverage category remains", "coverage"
            )
        if budget_spent:
            return CompletionVerdict(
                True, f"budget exhausted ({', '.join(snapshot.budget.exhausted)})", "budget"
            )
        if not runnable:
            return CompletionVerdict(True, "no runnable branches remain", "no_branches")
        return CompletionVerdict(
            False,
            f"{len(facts.insufficient_categories)} insufficient categor(y/ies), "
            f"{len(runnable)} runnable branch(es)",
        )


MODE_PROFILES: dict[CampaignMode, ModeProfile] = {
    CampaignMode.prove_or_refute: ModeProfile(
        CampaignMode.prove_or_refute, _PROVE_OR_REFUTE_RECIPE
    ),
    CampaignMode.exploration: ModeProfile(CampaignMode.exploration, _EXPLORATION_RECIPE),
    CampaignMode.survey: ModeProfile(CampaignMode.survey, _SURVEY_RECIPE),
}


def mode_profile(mode: CampaignMode | str) -> ModeProfile:
    return MODE_PROFILES[CampaignMode(str(mode))]


__all__ = [
    "CAMPAIGN_MACHINE",
    "MODE_PROFILES",
    "PHASE_TRANSITIONS",
    "ROOT_SETTLED_LABELS",
    "RUNNABLE_BRANCH_STATUSES",
    "TERMINAL_PHASES",
    "WORKING_PHASES",
    "CompletionVerdict",
    "DossierFacts",
    "InvalidTransition",
    "ModeProfile",
    "PortfolioRecipe",
    "allowed_targets",
    "assert_transition",
    "can_transition",
    "is_terminal",
    "mode_profile",
    "runnable_branches",
]
