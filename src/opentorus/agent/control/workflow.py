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
    """The first decision that is not a plain ``ALLOW``, else ``ALLOW``.

    A ``WARN`` counts as "not plain allow" so its message is not lost; callers that only
    care about blocking/stopping check ``.blocks``/``.stops`` on the result.
    """
    for decision in decisions:
        if not (decision.allows and not decision.message):
            return decision
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
    """Ask each member in order; the first non-allow answer wins.

    Members before the deciding one are still consulted (their hooks may keep state,
    e.g. a stall window anchors itself on every call), members after it are not.
    """

    def __init__(self, members: Sequence[WorkflowPolicySet]) -> None:
        self.members: list[WorkflowPolicySet] = list(members)

    @staticmethod
    def _ask(decisions: Iterable[PolicyDecision]) -> PolicyDecision:
        # A lazy generator comes in, so members after the deciding one are not asked.
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
