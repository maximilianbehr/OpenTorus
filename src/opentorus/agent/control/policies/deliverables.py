"""The deliverable policy: what a run must produce before it may end, and how it is nudged.

``AgentLoop`` took six loosely coupled callbacks for this (``deliverable_bootstrap``,
``session_gate``, ``session_recovery_hint``, ``pre_deliverable_gate``,
``pre_deliverable_gate_detail``, ``deliverable_complete``) and kept the "satisfied"
bit next to them. This object bundles the six plus the bit and answers the questions
the loop actually asks — is the session ready to end, does this turn need a
deliverable, which recovery hint, which bootstrap call, is the deliverable gated —
with exactly the answers the inline code gave.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from opentorus.agent.control.legacy import DEFAULT_HINTS, HintTexts, pre_deliverable_block_message
from opentorus.tools.base import ToolResult

if TYPE_CHECKING:
    from opentorus.research.tasks import Task


def default_satisfied_by(name: str, result: ToolResult) -> bool:
    """A primary-scope result satisfies the deliverable; an exploration one does not."""
    return result.metadata.get("scope", "primary") == "primary"


class DeliverablePolicy:
    def __init__(
        self,
        bootstrap: tuple[str, dict] | None = None,
        session_gate: Callable[[], bool] | None = None,
        session_recovery_hint: Callable[[], str] | None = None,
        pre_deliverable_gate: Callable[[], bool] | None = None,
        pre_deliverable_gate_detail: Callable[[], str] | None = None,
        deliverable_complete: Callable[[], bool] | None = None,
        *,
        satisfied_by: Callable[[str, ToolResult], bool] = default_satisfied_by,
        hints: HintTexts = DEFAULT_HINTS,
    ) -> None:
        self.bootstrap = bootstrap
        self.session_gate = session_gate
        self.session_recovery_hint = session_recovery_hint
        self.pre_deliverable_gate = pre_deliverable_gate
        self.pre_deliverable_gate_detail = pre_deliverable_gate_detail
        self.deliverable_complete = deliverable_complete
        self.satisfied_by = satisfied_by
        self.hints = hints
        # Fixed at construction on purpose: a caller that swaps ``bootstrap`` later
        # (tests do, to simulate gap-fill) does not thereby change which tool counts as
        # the deliverable — that is what the pre-extraction loop did.
        self.required_tool: str | None = bootstrap[0] if bootstrap is not None else None
        self.satisfied = False

    # --- state questions ---------------------------------------------------------

    def session_ready(self) -> bool:
        """May the run end with a final answer?"""
        if self.satisfied:
            if self.deliverable_complete is not None and not self.deliverable_complete():
                return False
            return True
        if self.session_gate is not None and self.session_gate():
            return True
        return False

    def needs_deliverable(self, planned_task: Task | None) -> bool:
        """Does this run have anything it must produce (task, bootstrap, or gate)?"""
        return (
            planned_task is not None or self.bootstrap is not None or self.session_gate is not None
        )

    def in_gap_fill(self) -> bool:
        """The deliverable exists but is not complete yet (e.g. a sketch with open gaps)."""
        return (
            self.satisfied
            and self.deliverable_complete is not None
            and not self.deliverable_complete()
        )

    def mark_satisfied(self) -> None:
        self.satisfied = True

    def note_deliverable_result(self, name: str, result: ToolResult) -> bool:
        """Mark the deliverable satisfied when its tool succeeded in primary scope."""
        if self.required_tool is not None and name == self.required_tool and result.ok:
            if self.satisfied_by(name, result):
                self.satisfied = True
                return True
        return False

    # --- what the model is told ------------------------------------------------------

    def recovery_hint(
        self, planned_task: Task | None, attempt: int, tool_calls_this_run: int
    ) -> str:
        """The hint for a chat-only turn while the deliverable is missing."""
        if planned_task is not None:
            from opentorus.agent.task_bootstrap import recovery_hint_for_task

            return recovery_hint_for_task(planned_task, attempt=attempt)
        if self.session_gate is not None:
            if self.session_recovery_hint is not None:
                return self.session_recovery_hint()
            if tool_calls_this_run > 0:
                return self.hints.lit_recovery_after_tools
            return self.hints.lit_recovery
        if self.in_gap_fill():
            return self.gap_fill_hint()
        if tool_calls_this_run > 0:
            return self.hints.prove_recovery_after_tools
        return self.hints.prove_recovery

    def gap_fill_hint(self) -> str:
        if self.session_recovery_hint is not None:
            return self.session_recovery_hint()
        return self.hints.prove_gaps_recovery

    def bootstrap_call(
        self, planned_task: Task | None, root: Path, ot_dir: Path
    ) -> tuple[str, dict] | None:
        """The tool call to fire when the model will not: per task, else the bootstrap.

        During gap-fill the bootstrap does not re-fire (it would overwrite the sketch
        the model is supposed to refine), so ``None`` comes back and the caller nudges
        instead.
        """
        if planned_task is not None:
            from opentorus.agent.task_bootstrap import bootstrap_tool_for_task

            return bootstrap_tool_for_task(planned_task, root, ot_dir)
        if self.bootstrap is not None and not self.in_gap_fill():
            return self.bootstrap
        return None

    def pre_gate_block(self, name: str) -> str | None:
        """The block text when the deliverable tool ran but its precondition is unmet."""
        if self.required_tool is None or name != self.required_tool:
            return None
        if self.pre_deliverable_gate is None or self.pre_deliverable_gate():
            return None
        detail = (
            self.pre_deliverable_gate_detail().strip()
            if self.pre_deliverable_gate_detail is not None
            else "Preconditions not met."
        )
        return pre_deliverable_block_message(name, detail)
