"""Budget policies: the bounds that hold no matter what the model does.

Steps, wall-clock seconds, governance token/cost budgets and an external cancellation
signal. Each is checked *between* turns — before spending on the next one — so a stop
never interrupts a call in flight; the provider timeout owns that.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterable
from pathlib import Path

from opentorus.agent.control.models import PolicyAction, PolicyDecision, ReasonCode
from opentorus.config import Config

STEP_CAP_MESSAGE = "Reached the maximum number of steps without a final answer."
CANCELLED_MESSAGE = "[stopped] cancelled by caller"


def _stop(reason: ReasonCode, message: str, **metadata: object) -> PolicyDecision:
    return PolicyDecision(
        action=PolicyAction.STOP, reason_code=reason, message=message, metadata=dict(metadata)
    )


class StepCapPolicy:
    """A finite ``max_steps`` is a hard cap; ``inf`` means unbounded.

    ``inf`` runs until the deliverable is done, a stall guard trips, or the user
    interrupts — the other policies are what make that honest.
    """

    def __init__(self, max_steps: float) -> None:
        self.max_steps = max_steps

    @property
    def unbounded(self) -> bool:
        return math.isinf(self.max_steps)

    def steps(self) -> Iterable[int]:
        """The step iterator the loop drives: endless when unbounded, else a range."""
        return itertools.count() if self.unbounded else range(int(self.max_steps))

    def check(self, steps_run: int) -> PolicyDecision | None:
        if self.unbounded or steps_run < self.max_steps:
            return None
        return _stop(ReasonCode.STEP_CAP_REACHED, STEP_CAP_MESSAGE, steps_run=steps_run)


class WallClockPolicy:
    """Stop once the run has spent its wall-clock budget.

    Every other guard — the chat-only streak, the identical-failure cap, the
    no-progress windows — assumes turns come back. A single model call that hangs
    satisfies none of them, and with ``max_steps: inf`` a run can repeat that
    indefinitely; only the provider timeout ends each individual call. This is the
    one bound that holds regardless of what the model does, so it is checked before
    spending on the next turn rather than in the middle of one.
    """

    def __init__(self, limit: float | None) -> None:
        self.limit = limit

    def check(self, elapsed: float, steps_run: int) -> PolicyDecision | None:
        limit = self.limit
        if limit is None or limit <= 0:
            return None
        if elapsed < limit:
            return None
        return _stop(
            ReasonCode.WALL_CLOCK_EXHAUSTED,
            f"Stopped: this run reached its wall-clock budget of {limit:.0f}s "
            f"(elapsed {elapsed:.0f}s) after {steps_run} model steps. Everything "
            "recorded so far is preserved; re-run to continue from the artifacts, or "
            "raise agent.max_wall_seconds.",
            limit=limit,
            elapsed=elapsed,
            steps_run=steps_run,
        )


class GovernanceBudgetPolicy:
    """Wraps ``governance.assert_within_budget``: a breached cap stops cleanly."""

    def __init__(self, ot_dir: Path, config: Config, session_id: str | None) -> None:
        self.ot_dir = ot_dir
        self.config = config
        self.session_id = session_id

    def check(self) -> PolicyDecision | None:
        from opentorus.governance import BudgetExceeded, assert_within_budget

        try:
            assert_within_budget(self.ot_dir, self.config, session_id=self.session_id)
        except BudgetExceeded as exc:
            return _stop(ReasonCode.BUDGET_EXHAUSTED, f"[stopped] {exc}")
        return None


class CancellationPolicy:
    """An external ``should_stop()`` — a campaign engine pausing, a user's Ctrl-C proxy."""

    def __init__(self, should_stop: Callable[[], bool] | None) -> None:
        self.should_stop = should_stop

    def check(self) -> PolicyDecision | None:
        if self.should_stop is None or not self.should_stop():
            return None
        return _stop(ReasonCode.CANCELLED, CANCELLED_MESSAGE)
