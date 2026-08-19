"""The agent control plane: typed decisions, policies, events, and the turn runner.

``AgentLoop`` remains the facade every caller uses; this package holds the pieces it
is assembled from so a campaign worker can compose the same guards, budgets and
deliverable rules without inheriting the loop's control flow. Nothing here changes
what a run says or records — the extraction is pinned by characterization tests.
"""

from opentorus.agent.control.events import (
    ListSink,
    NullSink,
    RunEvent,
    RunEventSink,
    RunStopped,
    ToolExecuted,
    TurnCompleted,
    TurnStarted,
)
from opentorus.agent.control.models import (
    PolicyAction,
    PolicyContext,
    PolicyDecision,
    ReasonCode,
    ToolOutcome,
)
from opentorus.agent.control.phase_machine import InvalidTransition, PhaseMachine
from opentorus.agent.control.workflow import (
    CompositePolicySet,
    NullPolicySet,
    WorkflowPolicySet,
    first_blocking,
)

__all__ = [
    "CompositePolicySet",
    "InvalidTransition",
    "ListSink",
    "NullPolicySet",
    "NullSink",
    "PhaseMachine",
    "PolicyAction",
    "PolicyContext",
    "PolicyDecision",
    "ReasonCode",
    "RunEvent",
    "RunEventSink",
    "RunStopped",
    "ToolExecuted",
    "ToolOutcome",
    "TurnCompleted",
    "TurnStarted",
    "WorkflowPolicySet",
    "first_blocking",
]
