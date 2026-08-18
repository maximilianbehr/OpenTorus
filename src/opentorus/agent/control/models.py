"""Typed decisions for the agent control plane.

Every guard in the agent loop used to answer in prose only: a string appended to a
tool result, or a stop message returned from ``run()``. The prose stays — it is what
the model reads and what recorded runs and their tests pin — but each decision now
also carries an *action* and a *reason code*, so a caller (a campaign worker, an
event sink, a dashboard) can act on the decision without parsing English.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field


class PolicyAction(StrEnum):
    """What a policy asks the loop to do with the thing it evaluated."""

    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"
    PAUSE = "pause"
    STOP = "stop"


class ReasonCode(StrEnum):
    """Machine-readable cause behind a decision; the message stays the human one."""

    REPEATED_IDENTICAL_FAILURE = "REPEATED_IDENTICAL_FAILURE"
    UNCHANGED_ERROR_OUTPUT = "UNCHANGED_ERROR_OUTPUT"
    SEARCH_STREAK_LIMIT = "SEARCH_STREAK_LIMIT"
    LOW_ACQUISITION_RATIO = "LOW_ACQUISITION_RATIO"
    CACHED_SOURCE_REREAD = "CACHED_SOURCE_REREAD"
    NO_ARTIFACT_PROGRESS = "NO_ARTIFACT_PROGRESS"
    REPEATED_STRATEGY = "REPEATED_STRATEGY"
    REPEATED_UNVERIFIABLE_CLAIM = "REPEATED_UNVERIFIABLE_CLAIM"
    BRANCH_EXHAUSTED = "BRANCH_EXHAUSTED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    WALL_CLOCK_EXHAUSTED = "WALL_CLOCK_EXHAUSTED"
    STEP_CAP_REACHED = "STEP_CAP_REACHED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    EGRESS_BLOCKED = "EGRESS_BLOCKED"
    TOOL_GATE_BLOCKED = "TOOL_GATE_BLOCKED"
    DELIVERABLE_MISSING = "DELIVERABLE_MISSING"
    CANCELLED = "CANCELLED"
    PORTFOLIO_CAP = "PORTFOLIO_CAP"
    OK = "OK"


class PolicyDecision(BaseModel):
    """One policy's verdict: the action, why, and the exact text the model sees.

    ``message`` is the byte-for-byte text the pre-existing loop produced for the same
    situation — nudges, stop messages, block reasons — so moving a guard behind a
    decision never changes what a run says.
    """

    action: PolicyAction
    reason_code: ReasonCode
    message: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def stops(self) -> bool:
        """True when the run must end (``STOP``) or hold (``PAUSE``)."""
        return self.action in (PolicyAction.STOP, PolicyAction.PAUSE)

    @property
    def blocks(self) -> bool:
        return self.action is PolicyAction.BLOCK

    @property
    def allows(self) -> bool:
        return self.action in (PolicyAction.ALLOW, PolicyAction.WARN)


ALLOW = PolicyDecision(action=PolicyAction.ALLOW, reason_code=ReasonCode.OK)


def allow(message: str = "") -> PolicyDecision:
    """An ``ALLOW``/``OK`` decision (optionally carrying an informational message)."""
    return PolicyDecision(action=PolicyAction.ALLOW, reason_code=ReasonCode.OK, message=message)


@dataclass(frozen=True)
class PolicyContext:
    """Read-only view of the loop counters a per-turn policy may consult."""

    steps_run: int
    tool_calls_this_run: int
    elapsed_seconds: float
    last_tool_ok: bool
    deliverable_satisfied: bool
    session_id: str


class ToolOutcome(BaseModel):
    """What one tool execution came to, as the loop and the event sink see it.

    ``content`` is the text handed back to the model (already annotated by the guards);
    ``blocked_by`` names the reason a call never ran; ``edited`` says whether the
    workspace may have changed; ``file_edit`` carries ``(path, old, new)`` for a write
    the caller records as a patch.
    """

    name: str
    args: dict = Field(default_factory=dict)
    ok: bool
    content: str
    blocked_by: ReasonCode | None = None
    edited: bool = False
    call_id: str = ""
    ran: bool = False
    file_edit: tuple[str, str, str] | None = None
    duration_ms: int = 0


class RoutingProvenance(Protocol):
    """The slice of a routing decision the usage ledger stamps onto every turn.

    ``providers.pool.RoutingDecisionRecord`` satisfies this structurally; the control
    plane deliberately depends only on the shape so it never imports the pool.
    """

    @property
    def decision_id(self) -> str | None: ...

    @property
    def task_class(self) -> str | None: ...

    @property
    def requested_profile(self) -> str | None: ...

    @property
    def selected_profile(self) -> str | None: ...

    @property
    def configured_model(self) -> str | None: ...

    @property
    def fallback_reason(self) -> str | None: ...
