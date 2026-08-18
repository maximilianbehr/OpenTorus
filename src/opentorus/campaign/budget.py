"""Campaign budgets: the ledger arithmetic and the exhaustion policy.

Every limit follows the config convention ``0 = not configured / unlimited``. The
unit of ``steps`` is one model turn; a work item that makes no model call is charged
one step so an offline campaign still terminates. Exhaustion is a
:class:`PolicyDecision` with ``BUDGET_EXHAUSTED`` and the axis in ``metadata`` — the
engine records ``budget_exhausted`` once per axis (the ledger's ``exhausted`` list)
and pauses the campaign; a resume that finds the same axes still spent lets the
mode's completion criterion end the campaign instead of pausing forever.

Wall-clock seconds are measured with the injected clock between work items; they are
recorded in ``budget_consumed`` events (so replay reproduces them) but excluded from
the structural digest tests compare, because on the real clock they vary run to run.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentorus.agent.control.models import PolicyAction, PolicyDecision, ReasonCode
from opentorus.campaign.models import (
    BudgetLedger,
    CampaignConfigSnapshot,
    CampaignMode,
    CostTotals,
)
from opentorus.config import Config


def charge(
    ledger: BudgetLedger,
    scope: str,
    ref: str,
    *,
    steps: int = 0,
    tokens: int = 0,
    cost_usd: float = 0.0,
    wall_seconds: float = 0.0,
) -> BudgetLedger:
    """A charged *copy* of ``ledger`` (the reducer applies the same arithmetic to
    ``budget_consumed``; this helper exists for in-memory projections between events)."""
    new = ledger.model_copy(deep=True)
    new.steps_used += steps
    new.tokens_used += tokens
    new.cost_used_usd += cost_usd
    new.wall_seconds_used += wall_seconds
    if scope == "work_item" and ref:
        new.per_work_item[ref] = new.per_work_item.get(ref, CostTotals()).plus(
            steps=steps, tokens=tokens, cost_usd=cost_usd, wall_seconds=wall_seconds
        )
    elif scope == "branch" and ref:
        new.per_branch[ref] = new.per_branch.get(ref, CostTotals()).plus(
            steps=steps, tokens=tokens, cost_usd=cost_usd, wall_seconds=wall_seconds
        )
    elif scope == "model_invocation":
        new.model_invocations += 1
    elif scope == "tool_execution":
        new.tool_executions += 1
    elif scope == "experiment":
        new.experiments_run += 1
    return new


@dataclass(frozen=True)
class ExhaustedAxis:
    axis: str
    used: float
    limit: float


class CampaignBudgetPolicy:
    """Which budget axes are spent, as a policy decision.

    Axes: ``steps``, ``tokens``, ``cost_usd``, ``wall_seconds`` from the campaign's own
    limits, plus ``governance_tokens`` / ``governance_cost_usd`` from the governance caps
    frozen into the config snapshot (they bound the campaign as a whole; the per-work-item
    ``assert_within_budget`` check in the engine consults the usage ledger for the same
    caps across every session the campaign ran).
    """

    def __init__(
        self,
        config_snapshot: CampaignConfigSnapshot,
        ledger: BudgetLedger,
        *,
        governance_budgets: tuple[int | None, float | None] | None = None,
    ) -> None:
        self.config = config_snapshot
        self.ledger = ledger
        if governance_budgets is None:
            governance_budgets = (
                config_snapshot.governance_token_budget,
                config_snapshot.governance_cost_budget_usd,
            )
        self.governance_token_budget, self.governance_cost_budget = governance_budgets

    def exhausted_axes(self) -> list[ExhaustedAxis]:
        ledger = self.ledger
        out: list[ExhaustedAxis] = []
        if self.config.max_steps > 0 and ledger.steps_used >= self.config.max_steps:
            out.append(ExhaustedAxis("steps", ledger.steps_used, self.config.max_steps))
        if self.config.token_budget > 0 and ledger.tokens_used >= self.config.token_budget:
            out.append(ExhaustedAxis("tokens", ledger.tokens_used, self.config.token_budget))
        if self.config.cost_budget > 0 and ledger.cost_used_usd >= self.config.cost_budget:
            out.append(ExhaustedAxis("cost_usd", ledger.cost_used_usd, self.config.cost_budget))
        if (
            self.config.max_wall_seconds > 0
            and ledger.wall_seconds_used >= self.config.max_wall_seconds
        ):
            out.append(
                ExhaustedAxis(
                    "wall_seconds", ledger.wall_seconds_used, self.config.max_wall_seconds
                )
            )
        gt = self.governance_token_budget
        if gt is not None and gt > 0 and ledger.tokens_used >= gt:
            out.append(ExhaustedAxis("governance_tokens", ledger.tokens_used, gt))
        gc = self.governance_cost_budget
        if gc is not None and gc > 0 and ledger.cost_used_usd >= gc:
            out.append(ExhaustedAxis("governance_cost_usd", ledger.cost_used_usd, gc))
        return out

    def newly_exhausted(self) -> list[ExhaustedAxis]:
        """Axes spent now that have not yet been announced by a ``budget_exhausted``."""
        return [a for a in self.exhausted_axes() if a.axis not in self.ledger.exhausted]

    def check(self) -> PolicyDecision | None:
        axes = self.exhausted_axes()
        if not axes:
            return None
        first = axes[0]
        return PolicyDecision(
            action=PolicyAction.PAUSE,
            reason_code=ReasonCode.BUDGET_EXHAUSTED,
            message=(
                f"[paused] campaign budget exhausted on {first.axis}: {first.used:g} of "
                f"{first.limit:g}"
            ),
            metadata={
                "axis": first.axis,
                "used": first.used,
                "limit": first.limit,
                "axes": [a.axis for a in axes],
            },
        )

    def is_exhausted(self) -> bool:
        return bool(self.exhausted_axes())


def has_positive_budget(snapshot: CampaignConfigSnapshot) -> bool:
    return (
        snapshot.max_steps > 0
        or snapshot.token_budget > 0
        or snapshot.max_wall_seconds > 0
        or snapshot.cost_budget > 0
    )


def budget_from_config(
    config: Config,
    *,
    mode: CampaignMode | None = None,
    branches: int | None = None,
    max_steps: int | None = None,
    token_budget: int | None = None,
    max_wall_seconds: int | None = None,
    cost_budget: float | None = None,
) -> CampaignConfigSnapshot:
    """Merge ``config.campaign`` with CLI overrides into the frozen config snapshot.

    ``None`` means "not given on the command line" (use the config); an explicit ``0``
    means "unlimited on this axis" exactly like the config file. Governance caps are
    copied verbatim so the campaign carries the caps it ran under.
    """
    c = config.campaign
    return CampaignConfigSnapshot(
        mode=CampaignMode(str(mode)) if mode is not None else CampaignMode(str(c.default_mode)),
        initial_branches=int(branches) if branches is not None else c.initial_branches,
        max_active_branches=c.max_active_branches,
        max_parallel_workers=c.max_parallel_workers,
        max_steps=int(max_steps) if max_steps is not None else c.max_steps,
        max_wall_seconds=(
            int(max_wall_seconds) if max_wall_seconds is not None else c.max_wall_seconds
        ),
        token_budget=int(token_budget) if token_budget is not None else c.token_budget,
        cost_budget=float(cost_budget) if cost_budget is not None else c.cost_budget,
        branch_step_budget=c.branch_step_budget,
        require_literature_mapping=c.require_literature_mapping,
        require_root_relation=c.require_root_relation,
        persist_every_event=c.persist_every_event,
        scheduler_weights=c.scheduler_weights.model_copy(),
        governance_token_budget=config.governance.budgets.token_budget,
        governance_cost_budget_usd=config.governance.budgets.cost_budget_usd,
    )


__all__ = [
    "CampaignBudgetPolicy",
    "ExhaustedAxis",
    "budget_from_config",
    "charge",
    "has_positive_budget",
]
