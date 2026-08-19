"""Workflow policy sets: the hooks a workflow gets into the loop.

A *policy set* answers five questions the loop asks at fixed points: may the next turn
start, may this tool call run, what follows from a tool result, is the run still
making progress, and may it end. Each answer is a :class:`PolicyDecision`; the loop
only ever looks at ``action``/``message`` and never at who answered. Composing sets
lets a campaign worker stack its own rules on top of the loop's legacy callbacks.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from opentorus.agent.control.models import (
    ALLOW,
    PolicyContext,
    PolicyDecision,
    ToolOutcome,
)


class WorkflowPolicySet(Protocol):
    """The five hooks; every method returns a decision (``ALLOW`` when it has none)."""

    def before_turn(self, ctx: PolicyContext) -> PolicyDecision: ...

    def before_tool(self, name: str, args: dict) -> PolicyDecision: ...

    def after_tool(self, outcome: ToolOutcome) -> PolicyDecision: ...

    def evaluate_progress(self, ctx: PolicyContext) -> PolicyDecision: ...

    def evaluate_completion(self, ctx: PolicyContext) -> PolicyDecision: ...


def first_blocking(decisions: Iterable[PolicyDecision]) -> PolicyDecision:
    """Fold an ordered sequence of decisions into the one the loop acts on.

    Members are consulted in order until one **stops** or **blocks**; that decision
    is returned. A ``WARN`` (or an ``ALLOW`` that carries a message) does not
    short-circuit — later members must still get their say, otherwise a mere
    warning would silence a real block behind it — but its message is not lost
    either: every warning seen is collected into the returned decision's
    ``metadata["warnings"]``. Without a stop/block the result is the first warning
    (with all warnings attached), else ``ALLOW``.
    """
    warnings: list[str] = []
    first_warn: PolicyDecision | None = None
    for decision in decisions:
        if decision.blocks or decision.stops:
            if warnings:
                return decision.model_copy(
                    update={"metadata": {**decision.metadata, "warnings": list(warnings)}}
                )
            return decision
        if not (decision.allows and not decision.message):
            if decision.message:
                warnings.append(decision.message)
            if first_warn is None:
                first_warn = decision
    if first_warn is not None:
        return first_warn.model_copy(
            update={"metadata": {**first_warn.metadata, "warnings": list(warnings)}}
        )
    return ALLOW


class NullPolicySet:
    """A policy set with no opinions — the base every hook falls back to."""

    def before_turn(self, ctx: PolicyContext) -> PolicyDecision:
        return ALLOW

    def before_tool(self, name: str, args: dict) -> PolicyDecision:
        return ALLOW

    def after_tool(self, outcome: ToolOutcome) -> PolicyDecision:
        return ALLOW

    def evaluate_progress(self, ctx: PolicyContext) -> PolicyDecision:
        return ALLOW

    def evaluate_completion(self, ctx: PolicyContext) -> PolicyDecision:
        return ALLOW


class CompositePolicySet:
    """Ask each member in order; the first stop/block answer wins, warnings accumulate.

    Members before the deciding one are still consulted (their hooks may keep state,
    e.g. a stall window anchors itself on every call), members after it are not. A
    warning never ends the consultation (see :func:`first_blocking`).
    """

    def __init__(self, members: Sequence[WorkflowPolicySet]) -> None:
        self.members: list[WorkflowPolicySet] = list(members)

    @staticmethod
    def _ask(decisions: Iterable[PolicyDecision]) -> PolicyDecision:
        # A lazy generator comes in, so members after the stopping/blocking one are
        # not asked; a warning keeps the generator going.
        return first_blocking(decisions)

    def before_turn(self, ctx: PolicyContext) -> PolicyDecision:
        return self._ask(m.before_turn(ctx) for m in self.members)

    def before_tool(self, name: str, args: dict) -> PolicyDecision:
        return self._ask(m.before_tool(name, args) for m in self.members)

    def after_tool(self, outcome: ToolOutcome) -> PolicyDecision:
        return self._ask(m.after_tool(outcome) for m in self.members)

    def evaluate_progress(self, ctx: PolicyContext) -> PolicyDecision:
        return self._ask(m.evaluate_progress(ctx) for m in self.members)

    def evaluate_completion(self, ctx: PolicyContext) -> PolicyDecision:
        return self._ask(m.evaluate_completion(ctx) for m in self.members)
