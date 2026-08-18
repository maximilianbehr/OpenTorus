"""Portfolio construction: which branches a campaign opens.

M3 ships :func:`bootstrap_portfolio` — the deterministic single-branch bootstrap
(one *literature* branch, root relation ``supporting``, worked by the offline
librarian) that lets a campaign run end to end under the mock provider — plus the
generic pieces the M4 multi-branch pipeline slots into: :func:`dedup_proposals`
(Jaccard on normalised objectives, same kind and root relation → ``REPEATED_STRATEGY``)
and :func:`activate_initial` (top ``max_active_branches`` by priority, tie-break by id).
The M4 template/LLM strategist produces proposals; everything after that is here.

Branch ids are minted from the snapshot's ``BRANCH`` counter by the caller (the
engine) so a replay reproduces them; this module never reads a clock or the disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from opentorus.agent.control.models import ReasonCode
from opentorus.campaign import ids
from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignSnapshot,
    RootRelation,
    WorkerRole,
)

JACCARD_DUPLICATE_THRESHOLD = 0.8
_TOKEN = re.compile(r"[a-z0-9]+")

# Which worker owns a branch of each kind (M4 fills the remaining workers).
KIND_TO_ROLE: dict[BranchKind, WorkerRole] = {
    BranchKind.proof: WorkerRole.prover,
    BranchKind.counterexample: WorkerRole.falsifier,
    BranchKind.literature: WorkerRole.librarian,
    BranchKind.special_case: WorkerRole.prover,
    BranchKind.symbolic: WorkerRole.symbolic_experimenter,
    BranchKind.numerical: WorkerRole.numerical_experimenter,
    BranchKind.formalization: WorkerRole.formalizer,
    BranchKind.obstruction: WorkerRole.prover,
    BranchKind.synthesis: WorkerRole.synthesizer,
}


def normalize_objective(text: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(text.lower()))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


@dataclass
class DedupResult:
    accepted: list[BranchRecord] = field(default_factory=list)
    rejected: list[BranchRecord] = field(default_factory=list)  # status=rejected, duplicate_of set


def dedup_proposals(
    proposals: list[BranchRecord], *, threshold: float = JACCARD_DUPLICATE_THRESHOLD
) -> DedupResult:
    """First proposal wins; a later one with the same (kind, root_relation) and a
    Jaccard overlap ≥ ``threshold`` on its normalised objective is rejected as
    ``REPEATED_STRATEGY`` (kept, with ``duplicate_of`` naming the survivor)."""
    result = DedupResult()
    for proposal in proposals:
        tokens = normalize_objective(proposal.objective)
        dup: BranchRecord | None = None
        for kept in result.accepted:
            if kept.kind is not proposal.kind or kept.root_relation is not proposal.root_relation:
                continue
            if jaccard(tokens, normalize_objective(kept.objective)) >= threshold:
                dup = kept
                break
        if dup is None:
            result.accepted.append(proposal)
        else:
            result.rejected.append(
                proposal.model_copy(
                    update={
                        "status": BranchStatus.rejected,
                        "rejection_reason": ReasonCode.REPEATED_STRATEGY.value,
                        "duplicate_of": dup.branch_id,
                        "distinctness_note": (
                            f"objective overlaps {dup.branch_id} (Jaccard >= {threshold})"
                        ),
                    }
                )
            )
    return result


def activate_initial(accepted: list[BranchRecord], *, max_active: int) -> list[BranchRecord]:
    """The branches to activate first: top ``max_active`` by priority, ties by branch id.

    The remaining accepted branches stay ``proposed`` (queued) and are activated in
    REALLOCATE when a slot frees up.
    """
    if max_active <= 0:
        return []
    ordered = sorted(accepted, key=lambda b: (-b.priority, b.branch_id))
    return ordered[:max_active]


def bootstrap_portfolio(
    snapshot: CampaignSnapshot,
    *,
    mode: CampaignMode,
    coverage: list[str] | None = None,
) -> list[BranchRecord]:
    """The M3 portfolio: exactly one literature branch (``supporting``), priority 1.0.

    ``mode`` is accepted so the call site does not change when M4's per-mode recipe
    (``phases.ModeProfile.portfolio_recipe``) replaces this bootstrap; the bootstrap
    itself is the same for every mode.

    Its objective names the insufficient critical coverage categories, so the branch
    is a real task for the librarian and not a placeholder. Returns a proposal with the
    next ``BRANCH-`` id from the snapshot's counter and status ``proposed``; the engine
    records ``branch_proposed`` then ``branch_activated``.
    """
    insufficient = list(coverage or [])
    what = ", ".join(insufficient) if insufficient else "all critical categories"
    branch_id = ids.mint(snapshot.counters, ids.BRANCH_PREFIX)
    return [
        BranchRecord(
            branch_id=branch_id,
            campaign_id=snapshot.campaign_id,
            title="Literature map",
            kind=BranchKind.literature,
            objective=f"Map the literature for {snapshot.problem_id}: {what}",
            strategy_summary=(
                "Assess category coverage from local artifacts (papers, known results, "
                "theorem references); coverage stays at most partial until a reviewed "
                "theorem reference exists."
            ),
            root_relation=RootRelation.supporting,
            status=BranchStatus.proposed,
            priority=1.0,
            assigned_worker_role=WorkerRole.librarian,
            strategy_key="literature_map",
            estimated_cost=1.0,
        )
    ]


__all__ = [
    "JACCARD_DUPLICATE_THRESHOLD",
    "KIND_TO_ROLE",
    "DedupResult",
    "activate_initial",
    "bootstrap_portfolio",
    "dedup_proposals",
    "jaccard",
    "normalize_objective",
]
