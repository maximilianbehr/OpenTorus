"""Run events the agent loop emits, and the sink protocol that receives them.

The loop already persists everything to ``session.jsonl`` and ``actions.jsonl``; the
events here are the *typed, in-process* view of the same run, so a campaign engine
can drive its budget ledger and event log from what actually happened — without
re-reading the ledgers and without the loop knowing who is listening. The default
sink discards everything, so a plain ``run``/``prove`` records nothing new.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from opentorus.agent.control.models import PolicyDecision, ToolOutcome


class TurnStarted(BaseModel):
    """The loop is about to spend one model step."""

    kind: Literal["turn_started"] = "turn_started"
    step: int
    session_id: str


class TurnCompleted(BaseModel):
    """One provider turn came back and its usage was recorded."""

    kind: Literal["turn_completed"] = "turn_completed"
    step: int
    session_id: str
    response_kind: Literal["message", "tool_call"]
    tool_names: list[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_tokens: int = 0
    tokens_estimated: bool = True
    cost_usd: float = 0.0
    latency_ms: int = 0
    provider: str = "unknown"
    model: str = "unknown"
    actual_model: str | None = None
    routing_decision_id: str | None = None


class ToolExecuted(BaseModel):
    """One tool call went through the runner (ran, was blocked, or failed)."""

    kind: Literal["tool_executed"] = "tool_executed"
    step: int
    session_id: str
    outcome: ToolOutcome


class RunStopped(BaseModel):
    """``run()`` ended; ``decision`` says why (``OK`` for a clean final answer)."""

    kind: Literal["run_stopped"] = "run_stopped"
    step: int
    session_id: str
    decision: PolicyDecision


RunEvent = TurnStarted | TurnCompleted | ToolExecuted | RunStopped


class RunEventSink(Protocol):
    """Receives run events; must never raise into the loop."""

    def emit(self, event: RunEvent) -> None: ...


class NullSink:
    """The default: events go nowhere."""

    def emit(self, event: RunEvent) -> None:
        return None


class ListSink:
    """Keeps every event in order — for tests and for in-memory ledgers."""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def emit(self, event: RunEvent) -> None:
        self.events.append(event)

    def of_kind(self, kind: str) -> list[RunEvent]:
        return [e for e in self.events if e.kind == kind]

    def clear(self) -> None:
        self.events.clear()
