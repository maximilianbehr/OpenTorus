"""The strategist: portfolio proposals from a model, or the template.

Used by :func:`opentorus.campaign.portfolio.generate_portfolio`, not scheduled as a
branch worker. With a real provider it asks for a JSON array of proposals (task class
``campaign_strategy``) through a one-turn bounded loop — so the call is routed,
recorded in the usage ledger under the campaign's tags, and counted by the engine's
usage collector — and hands the *raw items* back; the portfolio module validates
them and applies the mandatory rules. With the mock provider it makes no call at
all: the template portfolio is the deterministic answer, and a note says so.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from opentorus.campaign.models import (
    BranchKind,
    CampaignMode,
    CostTotals,
    RootRelation,
    RoutingHint,
    WorkBudget,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import (
    WorkerRuntime,
    acquire_lease,
    bounded_loop,
    is_mock_provider,
)
from opentorus.errors import OpenTorusError

if TYPE_CHECKING:
    from opentorus.campaign.portfolio import PortfolioContext


KIND_ALIASES: dict[str, BranchKind] = {k.value: k for k in BranchKind} | {
    "special_case": BranchKind.special_case,
    "specialcase": BranchKind.special_case,
    "counter-example": BranchKind.counterexample,
    "formal": BranchKind.formalization,
    "numerics": BranchKind.numerical,
    "experiment": BranchKind.numerical,
    "lit": BranchKind.literature,
}
RELATION_ALIASES: dict[str, RootRelation] = {r.value: r for r in RootRelation} | {
    "special_case": RootRelation.special_case,
    "counterexample_route": RootRelation.counterexample_route,
    "counterexample": RootRelation.counterexample_route,
    "refutation": RootRelation.counterexample_route,
    "support": RootRelation.supporting,
    "supports": RootRelation.supporting,
    "equivalence": RootRelation.equivalent,
}


def parse_strategist_json(text: str) -> list[dict[str, object]]:
    """The JSON array in a model answer, tolerating prose and code fences around it."""
    if not text:
        return []
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def strategist_prompt(ctx: PortfolioContext) -> str:
    from opentorus.campaign.portfolio import PORTFOLIO_SLACK

    kinds = ", ".join(k.value for k in BranchKind)
    relations = ", ".join(r.value for r in RootRelation)
    problem = ctx.problem
    assumptions = "\n".join(f"- {a}" for a in problem.assumptions) or "- (none recorded)"
    coverage = ", ".join(ctx.coverage_insufficient) or "none"
    return (
        f"You are the strategist of a {CampaignMode(str(ctx.mode)).value} campaign on problem "
        f"{problem.problem_id}.\n\nStatement:\n{problem.statement}\n\n"
        f"Recorded assumptions:\n{assumptions}\n\n"
        f"Insufficient literature coverage categories: {coverage}\n\n"
        f"Propose {ctx.initial_branches + PORTFOLIO_SLACK} distinct lines of attack as a "
        'JSON array. Each element: {"title": str, "kind": one of [' + kinds + "], "
        '"objective": str, "strategy_summary": str, "root_relation": one of [' + relations + "], "
        '"assumption_context": [str], "why_distinct": str}. Include a proof route and a '
        "counterexample route; include a literature branch when coverage is insufficient. "
        "Answer with the JSON array only."
    )


def strategist_context(ctx: PortfolioContext) -> WorkerContext:
    """A worker context for the portfolio step (no branch, no work item)."""
    from opentorus.providers.pool import TaskClass

    return WorkerContext(
        campaign_id=ctx.campaign_id,
        branch_id=None,
        work_item_id=None,
        role=WorkerRole.strategist,
        task_class=TaskClass.campaign_strategy.value,
        mode=ctx.mode,
        root_problem=ctx.problem,
        budget=WorkBudget(max_steps=1),
        session_id=f"{ctx.campaign_id}:campaign:strategist",
        routing_hint=RoutingHint(required_capabilities=[]),
        insufficient_categories=tuple(ctx.coverage_insufficient),
    )


def propose_with_model(
    runtime: WorkerRuntime, ctx: PortfolioContext
) -> tuple[list[dict[str, object]], list[str]]:
    """``(items, notes)``: the strategist's JSON items, or none with a note saying why.

    Never raises for a provider problem — an unusable strategist is a template
    fallback with a note, not a failed campaign.
    """
    from opentorus.tools.registry import ToolRegistry

    wctx = strategist_context(ctx)
    try:
        lease = acquire_lease(wctx, runtime)
    except OpenTorusError as exc:
        return [], [f"strategist: no eligible provider ({exc}); template portfolio used"]
    if is_mock_provider(lease.provider):
        return [], ["strategist: mock provider; template portfolio used"]
    try:
        loop = bounded_loop(wctx, runtime, lease=lease, registry=ToolRegistry())
        answer = loop.run(strategist_prompt(ctx))
    except OpenTorusError as exc:
        return [], [f"strategist: provider error ({exc}); template portfolio used"]
    items = parse_strategist_json(answer)
    if not items:
        return [], ["strategist: answer was not a JSON array of proposals; template portfolio used"]
    return items, [
        f"strategist: {len(items)} proposal(s) from {lease.profile_name} "
        f"({lease.decision.decision_id})"
    ]


class StrategistWorker:
    """Registered for completeness: a strategist work item re-runs the proposal step
    and reports the items as notes (the engine's portfolio phase is the real caller)."""

    role = WorkerRole.strategist

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.campaign.portfolio import PortfolioContext

        pctx = PortfolioContext(
            campaign_id=ctx.campaign_id,
            mode=ctx.mode,
            problem=ctx.root_problem,
            coverage_insufficient=tuple(ctx.insufficient_categories),
        )
        items, notes = propose_with_model(rt, pctx)
        notes.append(f"{len(items)} strategist item(s)")
        return WorkerResult(status="completed", notes=notes, usage=CostTotals())


__all__ = [
    "KIND_ALIASES",
    "RELATION_ALIASES",
    "StrategistWorker",
    "parse_strategist_json",
    "propose_with_model",
    "strategist_context",
    "strategist_prompt",
]
