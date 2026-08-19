"""No-progress windows: stop when a measured quantity stops moving for ``window`` steps.

The prove loop had two of these as closures over dicts (the draft window and the
instance-gate window). Same semantics here, once: the first check anchors on the
current measurement; any *increase* re-anchors; ``window`` steps without one is a
stop. Whether the window is *active* at all (e.g. "only before a primary proof
exists") stays with the caller — an inactive window is simply not consulted, so it
never anchors either, exactly as before.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from opentorus.agent.control.models import PolicyAction, PolicyDecision, ReasonCode


class NoProgressWindow:
    def __init__(
        self,
        window: float,
        measure: Callable[[], int],
        message: Callable[[int], str],
        *,
        reason_code: ReasonCode = ReasonCode.NO_ARTIFACT_PROGRESS,
    ) -> None:
        self.window = window
        self.measure = measure
        self.message = message
        self.reason_code = reason_code
        self.best: int | None = None
        self.anchor_step: int | None = None

    @property
    def armed(self) -> bool:
        """True once the window has anchored on a first measurement."""
        return self.anchor_step is not None

    def reset(self) -> None:
        self.best = None
        self.anchor_step = None

    def check(self, step: int) -> PolicyDecision | None:
        """Consult the window at ``step``; ``None`` while progress is being made."""
        if math.isinf(self.window):
            return None
        progress = self.measure()
        if self.anchor_step is None or progress > (self.best or 0):
            self.best = progress
            self.anchor_step = step
            return None
        stalled = step - self.anchor_step
        if stalled < self.window:
            return None
        return PolicyDecision(
            action=PolicyAction.STOP,
            reason_code=self.reason_code,
            message=self.message(stalled),
            metadata={"stalled_steps": stalled, "window": self.window, "best": self.best},
        )
