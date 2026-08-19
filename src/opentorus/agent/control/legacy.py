"""The prove/literature texts and callback adapters the loop used to hard-code.

``AgentLoop`` grew five recovery hints and one gate message that only make sense for
``opentorus prove``; they lived next to the generic loop because that is where they
were used. They move here verbatim so the loop stays workflow-agnostic while every
existing import (``opentorus.agent.loop._PROVE_RECOVERY_HINT`` and friends) keeps
resolving to the same string. ``LegacyCallbackPolicySet`` wraps the old callback
keyword arguments (``tool_gate``, ``stall_check``, …) as a
:class:`~opentorus.agent.control.workflow.WorkflowPolicySet` so old and new callers
compose through one interface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from opentorus.agent.control.models import (
    ALLOW,
    PolicyAction,
    PolicyContext,
    PolicyDecision,
    ReasonCode,
    ToolOutcome,
)

PROVE_RECOVERY_HINT = (
    "This prove session requires a deliverable tool call — not a chat reply. "
    "Call proof_write(problem_id=…, scope=primary) with theorem restating the dossier, "
    "main_proof, and [GAP-n] markers."
)

PROVE_GAPS_RECOVERY_HINT = (
    "Primary proof_write exists but recorded gap(s) remain — this prove run is NOT complete. "
    "Read the latest PROOF-* and relevant PAPER-* notes; use paper_read, lit_search, "
    "paper_fetch, or exp_run as needed; then proof_write(scope=primary) to fill [GAP-n] "
    "or shrink the gap list. Do NOT reply with a summary until gaps are closed or you "
    "document a blocker in memory_add(kind=decisions)."
)

PROVE_RECOVERY_HINT_AFTER_TOOLS = (
    "This prove session is NOT complete. You used other tools but a primary proof_write "
    "is still mandatory. Call proof_write(scope=primary): restate the dossier in "
    "`theorem`, then main_proof with [GAP-n]. "
    "Speculative side threads (e.g. Fredholm, alternative formulations) belong in "
    "scope=exploration with connection_to_dossier — they do NOT finish the run alone. "
    "claim_new, and evidence_add alone do not finish a prove run."
)

LIT_RECOVERY_HINT = (
    "Literature phase requires tool calls — not a chat reply. "
    "Read the problem statement, run one lit_search with its technical terms only, "
    "then paper_fetch directly relevant hits. Do NOT call proof_write yet."
)

LIT_RECOVERY_HINT_AFTER_TOOLS = (
    "Literature phase is NOT complete. "
    "Use lit_search, paper_fetch, and paper_read as needed; "
    "when papers are [parsed], add memory_add(kind=observations) with PAPER-* refs. "
    "Do NOT call proof_write or end with a summary yet."
)


@dataclass(frozen=True)
class HintTexts:
    """The recovery hints a deliverable-driven loop hands the model on a chat-only turn."""

    prove_recovery: str = PROVE_RECOVERY_HINT
    prove_gaps_recovery: str = PROVE_GAPS_RECOVERY_HINT
    prove_recovery_after_tools: str = PROVE_RECOVERY_HINT_AFTER_TOOLS
    lit_recovery: str = LIT_RECOVERY_HINT
    lit_recovery_after_tools: str = LIT_RECOVERY_HINT_AFTER_TOOLS


DEFAULT_HINTS = HintTexts()


def pre_deliverable_block_message(name: str, detail: str) -> str:
    """The rejection a deliverable tool gets when its literature precondition fails.

    Today the only gated deliverable is ``proof_write``, so the text reads exactly as
    it always did; ``name`` keeps it honest for any other deliverable a caller gates.
    """
    return (
        f"Blocked {name}: literature requirements not met ({detail}). "
        "Complete lit_search, paper_fetch, and memory_add "
        "(one observation per parsed paper) before drafting a proof."
    )


class LegacyCallbackPolicySet:
    """The old ``AgentLoop`` callback kwargs, spoken as a policy set.

    * ``tool_gate(name, args) -> str | None`` → ``before_tool`` (``BLOCK`` /
      ``TOOL_GATE_BLOCKED`` with the gate's text);
    * ``stall_check() -> str | None`` → ``before_turn`` (``STOP`` /
      ``NO_ARTIFACT_PROGRESS`` with the stall text);
    * ``session_gate`` / ``deliverable_complete`` → ``evaluate_completion``.

    The callables are looked up at call time, so a caller that swaps ``tool_gate``
    after construction (a few tests do) is honoured.
    """

    def __init__(
        self,
        *,
        tool_gate: Callable[[str, dict], str | None] | None = None,
        stall_check: Callable[[], str | None] | None = None,
        session_gate: Callable[[], bool] | None = None,
        deliverable_complete: Callable[[], bool] | None = None,
    ) -> None:
        self.tool_gate = tool_gate
        self.stall_check = stall_check
        self.session_gate = session_gate
        self.deliverable_complete = deliverable_complete

    def before_turn(self, ctx: PolicyContext) -> PolicyDecision:
        if self.stall_check is None:
            return ALLOW
        message = self.stall_check()
        if message is None:
            return ALLOW
        return PolicyDecision(
            action=PolicyAction.STOP, reason_code=ReasonCode.NO_ARTIFACT_PROGRESS, message=message
        )

    def before_tool(self, name: str, args: dict) -> PolicyDecision:
        if self.tool_gate is None:
            return ALLOW
        blocked = self.tool_gate(name, args)
        if blocked is None:
            return ALLOW
        return PolicyDecision(
            action=PolicyAction.BLOCK, reason_code=ReasonCode.TOOL_GATE_BLOCKED, message=blocked
        )

    def after_tool(self, outcome: ToolOutcome) -> PolicyDecision:
        return ALLOW

    def evaluate_progress(self, ctx: PolicyContext) -> PolicyDecision:
        return ALLOW

    def evaluate_completion(self, ctx: PolicyContext) -> PolicyDecision:
        if ctx.deliverable_satisfied:
            if self.deliverable_complete is not None and not self.deliverable_complete():
                return PolicyDecision(
                    action=PolicyAction.BLOCK,
                    reason_code=ReasonCode.DELIVERABLE_MISSING,
                    message="deliverable exists but is not complete",
                )
            return ALLOW
        if self.session_gate is not None and self.session_gate():
            return ALLOW
        if self.session_gate is None and self.deliverable_complete is None:
            return ALLOW
        return PolicyDecision(
            action=PolicyAction.BLOCK,
            reason_code=ReasonCode.DELIVERABLE_MISSING,
            message="deliverable not produced yet",
        )
