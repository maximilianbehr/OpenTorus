"""Which branch works next.

M3 semantics (documented, deterministic): among *active* branches with remaining
branch step budget, pick the one with the fewest work items so far — the fairness
factor of the full heuristic — and break ties by ``branch_id``. The returned
:class:`ScoreBreakdown` carries the factors that are already known (fairness,
literature boost, cost) so a status view can explain the choice; M4 replaces the
score with the documented weighted formula (root impact, info gain, novelty, …) and
keeps this signature.

The scheduler never mints ids and never touches the disk: it reads the snapshot and
the dossier facts the engine hands it and returns a plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignSnapshot,
    ScoreBreakdown,
    WorkerRole,
)
from opentorus.campaign.phases import DossierFacts
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


@dataclass(frozen=True)
class WorkItemPlan:
    branch_id: str
    role: WorkerRole
    task_class: str
    objective: str
    score: ScoreBreakdown
    max_steps: int


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


def select_next(
    snapshot: CampaignSnapshot,
    weights: SchedulerWeights,
    mode: CampaignMode,
    facts: DossierFacts,
    *,
    branch_step_budget: int = 0,
) -> WorkItemPlan | None:
    """The next work item, or ``None`` when nothing is runnable.

    Runnable = ``active`` and branch budget left and campaign budget left. Choice =
    fewest work items (fairness), then literature branches first while coverage is
    insufficient (literature boost), then lowest ``branch_id``.
    """
    if campaign_steps_remaining(snapshot) <= 0:
        return None
    literature_needed = bool(facts.insufficient_categories) or mode is CampaignMode.survey
    candidates: list[tuple[tuple[int, float, str], BranchRecord, ScoreBreakdown]] = []
    for bid in sorted(snapshot.branches):
        branch = snapshot.branches[bid]
        if branch.status is not BranchStatus.active:
            continue
        remaining = branch_steps_remaining(branch, snapshot, branch_step_budget)
        if remaining <= 0:
            continue
        items = len(branch.work_item_ids)
        boost = 1.0 if (literature_needed and branch.kind is BranchKind.literature) else 0.0
        cost = branch.estimated_cost / branch_step_budget if branch_step_budget > 0 else 0.0
        score = ScoreBreakdown(
            fairness=1.0 if items == 0 else 1.0 / (1 + items),
            literature_boost=boost,
            cost=cost,
            novelty=1.0 if items == 0 else 0.5**items,
            total=0.0,
            tie_break=bid,
        )
        score.total = score.fairness + score.literature_boost - weights.cost * score.cost
        candidates.append(((items, -boost, bid), branch, score))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    _key, branch, score = candidates[0]
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


__all__ = [
    "ROLE_TASK_CLASS",
    "WorkItemPlan",
    "branch_steps_remaining",
    "campaign_steps_remaining",
    "select_next",
]
