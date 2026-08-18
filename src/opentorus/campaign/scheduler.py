"""Which branch works next: a scored, documented heuristic — not a probability model.

Every factor below is a *heuristic* the operator can read off ``ScoreBreakdown`` in
``work_item_scheduled`` and reweight through ``campaign.scheduler_weights``. None of
them is a calibrated probability; ``resolve_chance`` in particular is a fixed
kind × mode table expressing which branch kinds tend to settle which campaign modes,
not an estimate about *this* problem. The scheduler never mints ids and never touches
the disk: it reads the snapshot and the derived dossier facts the engine hands it and
returns a plan.

Factors (all in ``[0, 1]`` unless noted; ``w_*`` are the config weights):

* ``root_impact`` — by ``root_relation``: equivalent 1.0, counterexample-route 0.9,
  sufficient 0.8, necessary 0.5, supporting 0.4, special-case / relaxation 0.3,
  unknown / unrelated 0.2. Settling a branch that settles the root is worth more.
* ``info_gain`` — ``1 / (1 + completed work items of the branch)``: the first work
  item on a branch teaches the most.
* ``resolve_chance`` — kind × mode table (:data:`RESOLVE_CHANCE`).
* ``verifier_readiness`` — 1.0 when the branch holds an artifact awaiting
  verification (a proof attempt with no open gaps, or a counterexample candidate),
  else 0.0: cheap to check, high value if it passes.
* ``novelty`` — ``0.5 ** (work items so far)``: repeated attention decays.
* ``dependency_criticality`` — ``1 + 0.5 × number of branches depending on it``
  (may exceed 1): unblocking others first.
* ``cost`` — ``estimated_cost / branch_step_budget`` (0 when the budget is
  unlimited): a penalty.
* ``redundancy`` — max token-set Jaccard of the objective against every *other*
  active branch: a penalty for near-duplicates that survived dedup.
* ``failure_risk`` — ``min(1, consecutive_failures / 3)``: a penalty.
* ``fairness`` — 1.0 when the branch has no more work items than the least-worked
  active branch, else 0.0: spreads the first round over distinct branches.
* ``literature_boost`` — 1.0 for literature branches while any critical coverage
  category is insufficient (or the mode is ``survey``): the map comes first.

``total = w_root·(root_impact + info_gain + resolve_chance)/3 + w_ver·verifier_readiness
+ w_nov·novelty + w_dep·dependency_criticality + fairness + literature_boost
− w_cost·cost − w_red·redundancy − w_fail·failure_risk``; ties break by ``branch_id``,
then ``work_item_id``.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignSnapshot,
    ClosureMode,
    ObligationStatus,
    ReactivationCondition,
    RootRelation,
    ScoreBreakdown,
    WorkerRole,
    WorkItemStatus,
)
from opentorus.campaign.phases import DossierFacts
from opentorus.campaign.portfolio import jaccard, normalize_objective
from opentorus.config import SchedulerWeights
from opentorus.providers.pool import TaskClass

# The provider task class each worker role asks the pool for.
ROLE_TASK_CLASS: dict[WorkerRole, TaskClass] = {
    WorkerRole.strategist: TaskClass.campaign_strategy,
    WorkerRole.prover: TaskClass.proof_development,
    WorkerRole.falsifier: TaskClass.counterexample_search,
    WorkerRole.librarian: TaskClass.literature_synthesis,
    WorkerRole.symbolic_experimenter: TaskClass.symbolic_experiment_design,
    WorkerRole.numerical_experimenter: TaskClass.numerical_experiment_design,
    WorkerRole.formalizer: TaskClass.formalization,
    WorkerRole.critic: TaskClass.adversarial_critique,
    WorkerRole.verifier_coordinator: TaskClass.verification_support,
    WorkerRole.synthesizer: TaskClass.final_synthesis,
}

ROOT_IMPACT: dict[RootRelation, float] = {
    RootRelation.equivalent: 1.0,
    RootRelation.counterexample_route: 0.9,
    RootRelation.sufficient: 0.8,
    RootRelation.necessary: 0.5,
    RootRelation.supporting: 0.4,
    RootRelation.special_case: 0.3,
    RootRelation.relaxation: 0.3,
    RootRelation.unknown: 0.2,
    RootRelation.unrelated: 0.2,
}

# kind × mode: which branch kinds tend to settle which modes. A documented heuristic
# table, not a probability about the problem at hand.
RESOLVE_CHANCE: dict[CampaignMode, dict[BranchKind, float]] = {
    CampaignMode.prove_or_refute: {
        BranchKind.proof: 0.6,
        BranchKind.counterexample: 0.6,
        BranchKind.formalization: 0.5,
        BranchKind.literature: 0.3,
        BranchKind.special_case: 0.3,
        BranchKind.symbolic: 0.3,
        BranchKind.obstruction: 0.2,
        BranchKind.numerical: 0.2,
        BranchKind.synthesis: 0.1,
    },
    CampaignMode.exploration: {
        BranchKind.numerical: 0.6,
        BranchKind.counterexample: 0.6,
        BranchKind.literature: 0.5,
        BranchKind.special_case: 0.4,
        BranchKind.symbolic: 0.4,
        BranchKind.proof: 0.3,
        BranchKind.obstruction: 0.3,
        BranchKind.formalization: 0.2,
        BranchKind.synthesis: 0.2,
    },
    CampaignMode.survey: {
        BranchKind.literature: 0.8,
        BranchKind.synthesis: 0.7,
        BranchKind.proof: 0.1,
        BranchKind.counterexample: 0.1,
        BranchKind.formalization: 0.1,
        BranchKind.special_case: 0.1,
        BranchKind.symbolic: 0.1,
        BranchKind.obstruction: 0.1,
        BranchKind.numerical: 0.1,
    },
}
DEFAULT_RESOLVE_CHANCE = 0.2


@dataclass(frozen=True)
class WorkItemPlan:
    branch_id: str
    role: WorkerRole
    task_class: str
    objective: str
    score: ScoreBreakdown
    max_steps: int


# --------------------------------------------------------------------------------------
# budgets
# --------------------------------------------------------------------------------------


def branch_steps_remaining(branch: BranchRecord, snapshot: CampaignSnapshot, budget: int) -> int:
    """Steps this branch may still spend (``budget <= 0`` = unlimited → a large number)."""
    if budget <= 0:
        return 10**9
    used = snapshot.budget.per_branch.get(branch.branch_id)
    return max(0, budget - (used.steps if used is not None else 0))


def campaign_steps_remaining(snapshot: CampaignSnapshot) -> int:
    limit = snapshot.budget.steps_limit
    if limit <= 0:
        return 10**9
    return max(0, limit - snapshot.budget.steps_used)


# --------------------------------------------------------------------------------------
# factors
# --------------------------------------------------------------------------------------


def _completed_items(branch: BranchRecord, snapshot: CampaignSnapshot) -> int:
    return sum(
        1
        for wid in branch.work_item_ids
        if (wi := snapshot.work_items.get(wid)) is not None
        and wi.status is WorkItemStatus.completed
    )


def _awaiting_verification(branch: BranchRecord, snapshot: CampaignSnapshot) -> bool:
    """Does the branch hold an artifact a verifier could act on right now?

    Snapshot-only (the scheduler reads no dossier): an open obligation of the branch
    that a *whole* proof attempt is meant to discharge (``source_proof_id`` set, no
    gap marker — i.e. the attempt is gap-free) or one whose closure mode is the
    counterexample certificate and that already cites a candidate; or a workspace
    ``PROOF-*`` the branch produced that no ``verification_recorded`` covers yet.
    """
    for ob in snapshot.obligations.values():
        if ob.branch_id != branch.branch_id:
            continue
        if ob.status not in (ObligationStatus.open, ObligationStatus.in_progress):
            continue
        if ob.gap_marker is None and ob.source_proof_id:
            return True
        if ClosureMode.accepted_counterexample_certificate in ob.closure_modes and (
            ob.supporting_artifacts
        ):
            return True
    verified = {v.artifact_id for v in snapshot.verifications}
    for ref in snapshot.artifact_refs:
        if ref.branch_id != branch.branch_id:
            continue
        if ref.kind == "proof" and ref.artifact_id not in verified:
            return True
    return False


def _dependents(branch: BranchRecord, snapshot: CampaignSnapshot) -> int:
    return sum(
        1
        for other in snapshot.branches.values()
        if other.branch_id != branch.branch_id
        and branch.branch_id in other.dependencies
        and other.status in (BranchStatus.active, BranchStatus.proposed, BranchStatus.suspended)
    )


def _redundancy(branch: BranchRecord, snapshot: CampaignSnapshot) -> float:
    mine = normalize_objective(branch.objective)
    best = 0.0
    for other in snapshot.branches.values():
        if other.branch_id == branch.branch_id or other.status is not BranchStatus.active:
            continue
        best = max(best, jaccard(mine, normalize_objective(other.objective)))
    return round(best, 4)


def _min_active_items(snapshot: CampaignSnapshot) -> int:
    counts = [
        len(b.work_item_ids) for b in snapshot.branches.values() if b.status is BranchStatus.active
    ]
    return min(counts) if counts else 0


def score_branch(
    branch: BranchRecord,
    snapshot: CampaignSnapshot,
    weights: SchedulerWeights,
    mode: CampaignMode,
    facts: DossierFacts,
    *,
    branch_step_budget: int = 0,
) -> ScoreBreakdown:
    """The documented factors and their weighted total for one branch."""
    items = len(branch.work_item_ids)
    literature_needed = bool(facts.insufficient_categories) or mode is CampaignMode.survey
    root_impact = ROOT_IMPACT.get(branch.root_relation, 0.2)
    info_gain = 1.0 / (1 + _completed_items(branch, snapshot))
    resolve_chance = RESOLVE_CHANCE.get(mode, {}).get(branch.kind, DEFAULT_RESOLVE_CHANCE)
    verifier_readiness = 1.0 if _awaiting_verification(branch, snapshot) else 0.0
    novelty = 0.5**items
    dependency_criticality = 1.0 + 0.5 * _dependents(branch, snapshot)
    cost = branch.estimated_cost / branch_step_budget if branch_step_budget > 0 else 0.0
    redundancy = _redundancy(branch, snapshot)
    failure_risk = min(1.0, branch.consecutive_failures / 3.0)
    fairness = 1.0 if items <= _min_active_items(snapshot) else 0.0
    literature_boost = 1.0 if (literature_needed and branch.kind is BranchKind.literature) else 0.0
    total = (
        weights.root_impact * (root_impact + info_gain + resolve_chance) / 3.0
        + weights.verifier_readiness * verifier_readiness
        + weights.novelty * novelty
        + weights.dependency * dependency_criticality
        + fairness
        + literature_boost
        - weights.cost * cost
        - weights.redundancy * redundancy
        - weights.failure * failure_risk
    )
    return ScoreBreakdown(
        root_impact=root_impact,
        info_gain=round(info_gain, 6),
        resolve_chance=resolve_chance,
        verifier_readiness=verifier_readiness,
        novelty=round(novelty, 6),
        dependency_criticality=dependency_criticality,
        cost=round(cost, 6),
        redundancy=redundancy,
        failure_risk=round(failure_risk, 6),
        literature_boost=literature_boost,
        fairness=fairness,
        total=round(total, 6),
        tie_break=branch.branch_id,
    )


# --------------------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------------------


def _dependencies_satisfied(branch: BranchRecord, snapshot: CampaignSnapshot) -> bool:
    for dep in branch.dependencies:
        other = snapshot.branches.get(dep)
        if other is None or other.status is not BranchStatus.completed:
            return False
    return True


def select_next(
    snapshot: CampaignSnapshot,
    weights: SchedulerWeights,
    mode: CampaignMode,
    facts: DossierFacts,
    *,
    branch_step_budget: int = 0,
    exclude: frozenset[str] | set[str] = frozenset(),
) -> WorkItemPlan | None:
    """The next work item, or ``None`` when nothing is runnable.

    Runnable = ``active``, branch step budget left, campaign step budget left,
    dependencies completed, not in ``exclude`` (branches the engine refused this
    round). Choice = highest ``total``; ties by ``branch_id`` (the plan carries no
    work item id yet — the engine mints it — so the second tie-break is applied by
    the caller's id order).
    """
    if campaign_steps_remaining(snapshot) <= 0:
        return None
    candidates: list[tuple[float, str, BranchRecord, ScoreBreakdown]] = []
    for bid in sorted(snapshot.branches):
        branch = snapshot.branches[bid]
        if branch.status is not BranchStatus.active or bid in exclude:
            continue
        if branch_steps_remaining(branch, snapshot, branch_step_budget) <= 0:
            continue
        if not _dependencies_satisfied(branch, snapshot):
            continue
        score = score_branch(
            branch, snapshot, weights, mode, facts, branch_step_budget=branch_step_budget
        )
        candidates.append((-score.total, bid, branch, score))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    _neg, _bid, branch, score = candidates[0]
    role = branch.assigned_worker_role
    max_steps = min(
        branch_steps_remaining(branch, snapshot, branch_step_budget),
        campaign_steps_remaining(snapshot),
    )
    return WorkItemPlan(
        branch_id=branch.branch_id,
        role=role,
        task_class=ROLE_TASK_CLASS.get(role, TaskClass.default).value,
        objective=branch.objective,
        score=score,
        max_steps=max(1, min(max_steps, 10**6)),
    )


# --------------------------------------------------------------------------------------
# suspension / reactivation
# --------------------------------------------------------------------------------------


def identical_failure_streak(
    branch: BranchRecord, snapshot: CampaignSnapshot
) -> tuple[int, str | None]:
    """``(length, key)`` of the trailing run of failed work items sharing one signature key.

    Only the branch's most recent work items count, in id order; a completed item
    breaks the streak. Items that failed without a signature (worker crash) count as
    failures but carry no key, so they never form an *identical* streak.
    """
    streak = 0
    key: str | None = None
    for wid in sorted(branch.work_item_ids, reverse=True):
        item = snapshot.work_items.get(wid)
        if item is None or item.status in (WorkItemStatus.created, WorkItemStatus.scheduled):
            continue
        if item.status is not WorkItemStatus.failed:
            break
        sig = (
            snapshot.failure_signatures.get(item.failure_signature_id)
            if item.failure_signature_id
            else None
        )
        this_key = sig.key if sig is not None else None
        if key is None:
            key = this_key
            streak = 1 if this_key is not None else 0
            if this_key is None:
                break
            continue
        if this_key != key:
            break
        streak += 1
    return streak, key


def reactivation_due(
    branch: BranchRecord, snapshot: CampaignSnapshot, facts: DossierFacts
) -> ReactivationCondition | None:
    """The first recorded reactivation condition that the current facts satisfy.

    Evaluates *recorded* conditions only — nothing is inferred from the branch's
    history: ``verification_backend_changed`` compares the enabled backends with the
    ones recorded at suspension; ``new_evidence_count`` and ``theorem_ref_accepted``
    compare the derived counts with their thresholds; ``branch_completed`` looks the
    referenced branch up; ``obligation_closed`` checks the named obligation;
    ``assumption_changed`` compares the branch's assumption context with the recorded
    one; ``human_override`` is never satisfied automatically.
    """
    for cond in branch.reactivation_conditions:
        if cond.kind == "verification_backend_changed":
            now = ",".join(sorted(facts.verifier_backends))
            if now != (cond.reference or ""):
                return cond
        elif cond.kind == "new_evidence_count":
            threshold = cond.threshold if cond.threshold is not None else 1.0
            if facts.evidence_count >= threshold:
                return cond
        elif cond.kind == "theorem_ref_accepted":
            threshold = cond.threshold if cond.threshold is not None else 1.0
            if facts.accepted_theorem_ref_count >= threshold:
                return cond
        elif cond.kind == "branch_completed":
            other = snapshot.branches.get(cond.reference or "")
            if other is not None and other.status is BranchStatus.completed:
                return cond
        elif cond.kind == "obligation_closed":
            ob = snapshot.obligations.get(cond.reference or "")
            if ob is not None and ob.status is ObligationStatus.closed:
                return cond
        elif cond.kind == "assumption_changed":
            recorded = cond.reference or ""
            if "|".join(sorted(branch.assumption_context)) != recorded:
                return cond
        # human_override: only a human decision reactivates; nothing to evaluate here.
    return None


__all__ = [
    "DEFAULT_RESOLVE_CHANCE",
    "RESOLVE_CHANCE",
    "ROLE_TASK_CLASS",
    "ROOT_IMPACT",
    "WorkItemPlan",
    "branch_steps_remaining",
    "campaign_steps_remaining",
    "identical_failure_streak",
    "reactivation_due",
    "score_branch",
    "select_next",
]
