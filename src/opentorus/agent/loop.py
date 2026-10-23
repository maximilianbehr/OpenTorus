"""The minimal agent loop.

The loop is provider-agnostic: it persists the user turn, asks the provider for
the next action, and either returns a message or routes a tool call through the
registry. Tool results are appended to the session and logged as actions. A step
cap prevents runaway loops.

Since the control-plane extraction this module is a *facade*: the guards live in
:mod:`opentorus.agent.control.policies` as pure objects, provider turns and tool
execution in :class:`opentorus.agent.control.turn_runner.TurnRunner`, and the
prove/literature hint texts in :mod:`opentorus.agent.control.legacy`. Every name a
caller or test reached for on ``AgentLoop`` — the constructor parameters, the
private counters, the guard constants imported from this module — keeps working
here by delegation, and every message a run produces is byte-identical.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from opentorus.agent.context import build_messages
from opentorus.agent.control import legacy as _legacy_texts
from opentorus.agent.control.events import RunEvent, RunEventSink, RunStopped, TurnStarted
from opentorus.agent.control.legacy import LegacyCallbackPolicySet
from opentorus.agent.control.models import (
    PolicyAction,
    PolicyContext,
    PolicyDecision,
    ReasonCode,
    RoutingProvenance,
)
from opentorus.agent.control.policies.anti_loop import (
    _ACQUISITION_MIN,
    _ACQUISITION_RATIO,
    _ACQUISITION_TOOLS,
    _IDENTICAL_FAILURE_WARN,
    _MAX_CACHED_RESERVES,
    _MAX_CHAT_ONLY_STALL,
    _MAX_DELIVERABLE_RETRIES,
    _MAX_IDENTICAL_FAILURES,
    _MAX_TOOL_PARSE_RETRIES,
    _MAX_UNCHANGED_ERROR_ATTEMPTS,
    _MAX_UNCHANGED_ERROR_STOP,
    _REPEAT_GUARD_EXEMPT,
    _REPEAT_GUARD_TOOLS,
    _SEARCH_STREAK_NEUTRAL,
    _SEARCH_STREAK_TOOLS,
    _SEARCH_STREAK_WARN,
    _VOLATILE_IN_ERRORS,
    AcquisitionGuard,
    ChatOnlyStallGuard,
    RepeatCallGuard,
    ToolFailureTracker,
    stable_error_key,
    tool_sig,
)
from opentorus.agent.control.policies.budget import (
    GovernanceBudgetPolicy,
    StepCapPolicy,
    WallClockPolicy,
)
from opentorus.agent.control.policies.deliverables import DeliverablePolicy
from opentorus.agent.control.turn_runner import (
    LLMRequestCallback,
    LLMResponseCallback,
    StatusCallback,
    TurnRunner,
    _shell_command_likely_edits,
)
from opentorus.agent.control.workflow import CompositePolicySet, WorkflowPolicySet
from opentorus.agent.prompts import LENGTH_CONTINUATION, TOOL_PARSE_RECOVERY
from opentorus.agent.session import SessionMessage, append_message
from opentorus.config import Config, OperatingStyle
from opentorus.errors import OpenTorusError, ProviderError, is_recoverable_tool_parse_error
from opentorus.permissions.policy import PermissionDecision
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.providers.retry import ContextLengthExceededError
from opentorus.tools.base import Tool
from opentorus.tools.jobs import drain_notices
from opentorus.tools.registry import ToolRegistry

# Results recorded for the calls of a batch that a cancel/interrupt cut short. The two
# cases are kept apart on purpose: a call that never started certainly had no effect; a
# call interrupted mid-run may have had any part of its effect.
TOOL_NOT_EXECUTED = "[not executed — cancelled before dispatch; this call did not run]"
TOOL_OUTCOME_UNKNOWN = (
    "[outcome unknown — interrupted while running; the call may have had some or all of "
    "its effect. Check the workspace state before repeating it.]"
)

# A confirmation callback receives the decision, a human-readable description
# of the pending action, and an optional session scope (e.g. "external" for all
# network tools). Returns True to allow it.
ConfirmCallback = Callable[[PermissionDecision, str, str | None], bool]

_logger = logging.getLogger(__name__)

# Historical names, kept importable from this module (tests and callers use them).
_stable_error_key = stable_error_key
_tool_sig = tool_sig
# The prove/literature recovery hints moved to control/legacy.py verbatim; the old
# private names resolve to the very same strings.
_PROVE_RECOVERY_HINT = _legacy_texts.PROVE_RECOVERY_HINT
_PROVE_GAPS_RECOVERY_HINT = _legacy_texts.PROVE_GAPS_RECOVERY_HINT
_PROVE_RECOVERY_HINT_AFTER_TOOLS = _legacy_texts.PROVE_RECOVERY_HINT_AFTER_TOOLS
_LIT_RECOVERY_HINT = _legacy_texts.LIT_RECOVERY_HINT
_LIT_RECOVERY_HINT_AFTER_TOOLS = _legacy_texts.LIT_RECOVERY_HINT_AFTER_TOOLS

__all__ = [
    "AgentLoop",
    "ConfirmCallback",
    "LLMRequestCallback",
    "LLMResponseCallback",
    "StatusCallback",
    "_ACQUISITION_MIN",
    "_ACQUISITION_RATIO",
    "_ACQUISITION_TOOLS",
    "_IDENTICAL_FAILURE_WARN",
    "_LIT_RECOVERY_HINT",
    "_LIT_RECOVERY_HINT_AFTER_TOOLS",
    "_MAX_CACHED_RESERVES",
    "_MAX_CHAT_ONLY_STALL",
    "_MAX_DELIVERABLE_RETRIES",
    "_MAX_IDENTICAL_FAILURES",
    "_MAX_TOOL_PARSE_RETRIES",
    "_MAX_UNCHANGED_ERROR_ATTEMPTS",
    "_MAX_UNCHANGED_ERROR_STOP",
    "_PROVE_GAPS_RECOVERY_HINT",
    "_PROVE_RECOVERY_HINT",
    "_PROVE_RECOVERY_HINT_AFTER_TOOLS",
    "_REPEAT_GUARD_EXEMPT",
    "_REPEAT_GUARD_TOOLS",
    "_SEARCH_STREAK_NEUTRAL",
    "_SEARCH_STREAK_TOOLS",
    "_SEARCH_STREAK_WARN",
    "_VOLATILE_IN_ERRORS",
    "_shell_command_likely_edits",
    "_stable_error_key",
    "_tool_sig",
]


class AgentLoop:
    def __init__(
        self,
        root: Path,
        ot_dir: Path,
        provider: BaseProvider,
        registry: ToolRegistry,
        config: Config,
        max_steps: float = 6,
        session_id: str | None = None,
        confirm: ConfirmCallback | None = None,
        on_text: Callable[[str], None] | None = None,
        on_status: StatusCallback | None = None,
        on_llm_request: LLMRequestCallback | None = None,
        on_llm_response: LLMResponseCallback | None = None,
        stream_llm: bool = False,
        on_thinking: Callable[[str], None] | None = None,
        deliverable_bootstrap: tuple[str, dict] | None = None,
        session_gate: Callable[[], bool] | None = None,
        session_recovery_hint: Callable[[], str] | None = None,
        pre_deliverable_gate: Callable[[], bool] | None = None,
        pre_deliverable_gate_detail: Callable[[], str] | None = None,
        deliverable_complete: Callable[[], bool] | None = None,
        tool_gate: Callable[[str, dict], str | None] | None = None,
        stall_check: Callable[[], str | None] | None = None,
        *,
        event_sink: RunEventSink | None = None,
        routing: RoutingProvenance | None = None,
        usage_tags: dict[str, str] | None = None,
        policies: WorkflowPolicySet | None = None,
        should_stop: Callable[[], bool] | None = None,
        isolate_history: bool | None = None,
    ) -> None:
        self.root = root
        self.ot_dir = ot_dir
        self.provider = provider
        self.registry = registry
        self.config = config
        self.max_steps = max_steps
        self.session_id = session_id or uuid.uuid4().hex
        # An isolated run (a campaign worker) sees only its own session's messages in
        # the history window; the default keeps the workspace-wide window the REPL and
        # ``run`` rely on for continuity across invocations.
        self.isolate_history = bool(isolate_history)
        self.confirm = confirm
        self.on_text = on_text
        self.on_status = on_status
        self.on_llm_request = on_llm_request
        self.on_llm_response = on_llm_response
        self.stream_llm = stream_llm
        self.on_thinking = on_thinking
        # What this run must produce, and how the model is nudged toward it.
        self._deliverable = DeliverablePolicy(
            deliverable_bootstrap,
            session_gate,
            session_recovery_hint,
            pre_deliverable_gate,
            pre_deliverable_gate_detail,
            deliverable_complete,
        )
        # The old callback kwargs (tool gate, caller-supplied stall detector) become the
        # first member of the policy set; a caller's own set stacks behind them.
        self._legacy = LegacyCallbackPolicySet(
            tool_gate=tool_gate,
            stall_check=stall_check,
            session_gate=session_gate,
            deliverable_complete=deliverable_complete,
        )
        members: list[WorkflowPolicySet] = [self._legacy]
        if policies is not None:
            members.append(policies)
        self._policies = CompositePolicySet(members)
        # Guards: pure objects the loop delegates to. The identical-failure memory and
        # the unchanged-error ledger deliberately survive across run() calls (see
        # ToolFailureTracker); the per-run counters are reset in run().
        self._tracker = ToolFailureTracker()
        self._repeat_guard = RepeatCallGuard()
        self._acquisition = AcquisitionGuard()
        self._chat_only = ChatOnlyStallGuard()
        self.event_sink = event_sink
        self.routing = routing
        self.usage_tags = dict(usage_tags or {})
        self.should_stop = should_stop
        self._runner = TurnRunner(
            root,
            ot_dir,
            provider,
            registry,
            config,
            session_id=self.session_id,
            confirm=confirm,
            on_text=on_text,
            on_status=on_status,
            on_llm_request=on_llm_request,
            on_llm_response=on_llm_response,
            stream_llm=stream_llm,
            on_thinking=on_thinking,
            policies=self._policies,
            deliverable=self._deliverable,
            repeat_guard=self._repeat_guard,
            failure_tracker=self._tracker,
            acquisition_guard=self._acquisition,
            event_sink=event_sink,
            routing=routing,
            usage_tags=usage_tags,
            should_stop=should_stop,
        )
        # State that must be usable before (and across) run().
        self.steps_run = 0
        self._task_id: str | None = None
        self.model_tool_calls = 0
        self.bootstrap_used = False
        self.hit_max_steps = False
        # Provider-reported size of the last request, and the ratio of that to the local
        # chars/4 estimate of the same request: the compaction trigger uses both, so it
        # measures the history in the tokens the provider actually counts.
        self._last_prompt_tokens: int | None = None
        self._token_scale: float | None = None

    # --- delegating surface (compatibility) -----------------------------------------------

    @property
    def _style(self) -> OperatingStyle:
        return self.config.agent.style

    @property
    def _review(self) -> bool:
        return self.config.agent.mode == "review"

    # deliverable policy
    @property
    def deliverable_bootstrap(self) -> tuple[str, dict] | None:
        return self._deliverable.bootstrap

    @deliverable_bootstrap.setter
    def deliverable_bootstrap(self, value: tuple[str, dict] | None) -> None:
        self._deliverable.bootstrap = value

    @property
    def session_gate(self) -> Callable[[], bool] | None:
        return self._deliverable.session_gate

    @session_gate.setter
    def session_gate(self, value: Callable[[], bool] | None) -> None:
        self._deliverable.session_gate = value
        self._legacy.session_gate = value

    @property
    def _session_recovery_hint(self) -> Callable[[], str] | None:
        return self._deliverable.session_recovery_hint

    @_session_recovery_hint.setter
    def _session_recovery_hint(self, value: Callable[[], str] | None) -> None:
        self._deliverable.session_recovery_hint = value

    @property
    def _pre_deliverable_gate(self) -> Callable[[], bool] | None:
        return self._deliverable.pre_deliverable_gate

    @_pre_deliverable_gate.setter
    def _pre_deliverable_gate(self, value: Callable[[], bool] | None) -> None:
        self._deliverable.pre_deliverable_gate = value

    @property
    def _pre_deliverable_gate_detail(self) -> Callable[[], str] | None:
        return self._deliverable.pre_deliverable_gate_detail

    @_pre_deliverable_gate_detail.setter
    def _pre_deliverable_gate_detail(self, value: Callable[[], str] | None) -> None:
        self._deliverable.pre_deliverable_gate_detail = value

    @property
    def _deliverable_complete(self) -> Callable[[], bool] | None:
        return self._deliverable.deliverable_complete

    @_deliverable_complete.setter
    def _deliverable_complete(self, value: Callable[[], bool] | None) -> None:
        self._deliverable.deliverable_complete = value
        self._legacy.deliverable_complete = value

    @property
    def _deliverable_satisfied(self) -> bool:
        return self._deliverable.satisfied

    @_deliverable_satisfied.setter
    def _deliverable_satisfied(self, value: bool) -> None:
        self._deliverable.satisfied = value

    @property
    def _required_deliverable_tool(self) -> str | None:
        return self._deliverable.required_tool

    # legacy callbacks
    @property
    def _tool_gate(self) -> Callable[[str, dict], str | None] | None:
        return self._legacy.tool_gate

    @_tool_gate.setter
    def _tool_gate(self, value: Callable[[str, dict], str | None] | None) -> None:
        self._legacy.tool_gate = value

    @property
    def _stall_check(self) -> Callable[[], str | None] | None:
        return self._legacy.stall_check

    @_stall_check.setter
    def _stall_check(self, value: Callable[[], str | None] | None) -> None:
        self._legacy.stall_check = value

    # runner counters
    @property
    def tool_calls_this_run(self) -> int:
        return self._runner.tool_calls_this_run

    @tool_calls_this_run.setter
    def tool_calls_this_run(self, value: int) -> None:
        self._runner.tool_calls_this_run = value

    @property
    def tools_used_this_run(self) -> list[str]:
        return self._runner.tools_used_this_run

    @tools_used_this_run.setter
    def tools_used_this_run(self, value: list[str]) -> None:
        self._runner.tools_used_this_run = value

    @property
    def edited(self) -> bool:
        return self._runner.edited

    @edited.setter
    def edited(self, value: bool) -> None:
        self._runner.edited = value

    @property
    def _pending_edits(self) -> list[tuple[str, str, str]]:
        return self._runner.pending_edits

    @_pending_edits.setter
    def _pending_edits(self, value: list[tuple[str, str, str]]) -> None:
        self._runner.pending_edits = value

    # failure tracker
    @property
    def _last_tool_ok(self) -> bool:
        return self._tracker.last_tool_ok

    @_last_tool_ok.setter
    def _last_tool_ok(self, value: bool) -> None:
        self._tracker.last_tool_ok = value

    @property
    def _fail_streak(self) -> int:
        return self._tracker.identical.streak

    @_fail_streak.setter
    def _fail_streak(self, value: int) -> None:
        self._tracker.identical.streak = value

    @property
    def _fail_streak_key(self) -> str | None:
        return self._tracker.identical.streak_key

    @_fail_streak_key.setter
    def _fail_streak_key(self, value: str | None) -> None:
        self._tracker.identical.streak_key = value

    @property
    def _fail_streak_tool(self) -> str | None:
        return self._tracker.identical.streak_tool

    @_fail_streak_tool.setter
    def _fail_streak_tool(self, value: str | None) -> None:
        self._tracker.identical.streak_tool = value

    @property
    def _failure_counts(self) -> dict[str, int]:
        return self._tracker.identical.failure_counts

    @_failure_counts.setter
    def _failure_counts(self, value: dict[str, int]) -> None:
        self._tracker.identical.failure_counts = value

    @property
    def _error_signatures(self) -> dict[str, set[str]]:
        return self._tracker.unchanged.error_signatures

    @_error_signatures.setter
    def _error_signatures(self, value: dict[str, set[str]]) -> None:
        self._tracker.unchanged.error_signatures = value

    @property
    def _unchanged_error_stop(self) -> str | None:
        stop = self._tracker.unchanged.stop
        return None if stop is None else stop.message

    # acquisition guard
    @property
    def _search_streak(self) -> int:
        return self._acquisition.search_streak

    @_search_streak.setter
    def _search_streak(self, value: int) -> None:
        self._acquisition.search_streak = value

    @property
    def _acquisition_calls(self) -> int:
        return self._acquisition.acquisition_calls

    @_acquisition_calls.setter
    def _acquisition_calls(self, value: int) -> None:
        self._acquisition.acquisition_calls = value

    @property
    def _processing_calls(self) -> int:
        return self._acquisition.processing_calls

    @_processing_calls.setter
    def _processing_calls(self, value: int) -> None:
        self._acquisition.processing_calls = value

    # repeat guard
    @property
    def _tool_sigs_ok(self) -> set[str]:
        return self._repeat_guard.tool_sigs_ok

    @_tool_sigs_ok.setter
    def _tool_sigs_ok(self, value: set[str]) -> None:
        self._repeat_guard.tool_sigs_ok = value

    @property
    def _read_fail_paths(self) -> set[str]:
        return self._repeat_guard.read_fail_paths

    @_read_fail_paths.setter
    def _read_fail_paths(self, value: set[str]) -> None:
        self._repeat_guard.read_fail_paths = value

    @property
    def _read_cache(self) -> dict[str, str]:
        return self._repeat_guard.read_cache

    @_read_cache.setter
    def _read_cache(self, value: dict[str, str]) -> None:
        self._repeat_guard.read_cache = value

    @property
    def _reserve_counts(self) -> dict[str, int]:
        return self._repeat_guard.reserve_counts

    @_reserve_counts.setter
    def _reserve_counts(self, value: dict[str, int]) -> None:
        self._repeat_guard.reserve_counts = value

    # --- delegating methods (compatibility) ---------------------------------------------

    def _note_tool_success(self, sig: str) -> None:
        """Reset the identical-failure streak when the streaking call finally succeeds."""
        self._tracker.note_success(sig)

    def _note_unchanged_error(self, name: str, sig: str, content: str) -> str:
        """Warn when new arguments keep producing the *same* error."""
        return self._tracker.unchanged.note(name, sig, content)

    def _acquisition_nudge(self, name: str) -> str | None:
        """Tell a collecting-but-not-reading run to stop collecting."""
        return self._acquisition.nudge(name)

    def _note_tool_failure(self, name: str, sig: str, content: str) -> str:
        """Track an identical failing (tool, args, error) triple; annotate from WARN on."""
        return self._tracker.note_failure(name, sig, content)

    def _identical_failure_stop(self) -> str | None:
        """Return an honest stop message once either dead-end cap is reached."""
        return self._tracker.stop_message()

    def _wall_clock_stop(self, run_started: float) -> str | None:
        """Stop once the run has spent its wall-clock budget."""
        limit = self.config.agent.max_wall_seconds
        if limit is None or limit <= 0:
            return None
        decision = WallClockPolicy(limit).check(time.monotonic() - run_started, self.steps_run)
        return None if decision is None else decision.message

    def _budget_stop(self) -> str | None:
        """Return a stop message if a configured budget cap is reached, else None."""
        decision = GovernanceBudgetPolicy(self.ot_dir, self.config, self.session_id).check()
        return None if decision is None else decision.message

    def _screen_outbound(self, messages) -> str | None:  # noqa: ANN001
        """Pre-egress DLP: block a cloud send that would leak secrets/PII (else None)."""
        decision = self._runner.screen_outbound(messages)
        return None if decision is None else decision.message

    def _record_usage(self, messages, response, elapsed: float) -> None:  # noqa: ANN001
        """Record a usage/cost entry for one provider turn."""
        self._runner.record_usage(messages, response, elapsed)

    def _read_path(self, user_path: str) -> str | None:
        return self._runner._read_path(user_path)

    def _evaluate(self, tool: Tool, args: dict) -> PermissionDecision | None:
        """Return a permission decision for a write/command tool, or None for reads."""
        return self._runner.evaluate(tool, args)

    def _enforce(self, name: str, args: dict, decision: PermissionDecision) -> str | None:
        """Apply a permission decision. Returns a message if the call must not run."""
        return self._runner.enforce(name, args, decision)

    def _run_tool(self, name: str, args: dict, call_id: str) -> str:
        """Execute one tool call and return the text handed back to the model."""
        self._runner.planned_task_id = self._task_id
        return self._runner.execute_tool(name, args, call_id).content

    # --- run ---------------------------------------------------------------------------------

    def _append(self, message: SessionMessage) -> None:
        message.metadata.setdefault("session_id", self.session_id)
        append_message(self.ot_dir, message)

    def _status(self, phase: str, detail: str | None = None) -> None:
        if self.on_status is not None:
            self.on_status(phase, detail)

    def _session_ready(self) -> bool:
        return self._deliverable.session_ready()

    def _context(self, run_started: float) -> PolicyContext:
        return PolicyContext(
            steps_run=self.steps_run,
            tool_calls_this_run=self.tool_calls_this_run,
            elapsed_seconds=time.monotonic() - run_started,
            last_tool_ok=self._last_tool_ok,
            deliverable_satisfied=self._deliverable_satisfied,
            session_id=self.session_id,
        )

    def _emit(self, event: RunEvent) -> None:
        """Hand an event to the sink without letting a sink failure end the run.

        ``events.RunEventSink`` says a sink never raises; the loop enforces it because
        it — not the sink — would otherwise lose the final answer.
        """
        if self.event_sink is None:
            return
        try:
            self.event_sink.emit(event)
        except Exception as exc:  # noqa: BLE001 — a sink must never abort the loop
            _logger.debug("Event sink raised on %s: %s", type(event).__name__, exc)

    def _emit_stop(self, decision: PolicyDecision) -> None:
        self._emit(RunStopped(step=self.steps_run, session_id=self.session_id, decision=decision))

    def _provider_kind(self) -> str:
        """The provider *kind* actually answering (``ollama``, ``openai``, ...).

        A routed lease is built from a profile, so the provider's own ``config`` is
        authoritative; a bare provider's ``name`` comes next; the workspace
        ``config.model.provider`` (the default profile) is the last resort. Deciding
        Ollama-only behaviour from the default profile would mis-drive a leased
        provider of another kind.
        """
        provider_cfg = getattr(getattr(self.provider, "config", None), "model", None)
        kind = getattr(provider_cfg, "provider", None) if provider_cfg is not None else None
        if not kind:
            kind = getattr(self.provider, "name", None)
        if not kind:
            kind = self.config.model.provider
        return str(kind)

    def _stop_run(self, decision: PolicyDecision) -> str:
        """Record a policy stop: append the message as the assistant turn, emit, log."""
        self._append(SessionMessage(role="assistant", content=decision.message))
        _logger.info("%s", decision.message)
        self._emit_stop(decision)
        return decision.message

    def run(self, task: str) -> str:
        """Run one task to completion and return the final assistant message."""
        self._append(SessionMessage(role="user", content=task))
        # Per-run reset of the counters and the per-run guard state. The identical-
        # failure memory and the unchanged-error ledger survive on purpose (see the
        # tracker); the failure *streak*, the search streak, the acquisition totals,
        # the read cache and the repeat signatures start fresh.
        self._runner.reset_run()
        self._runner.planned_task_id = self._task_id
        self._chat_only.reset()
        # Tool calls the model produced on its own, excluding bootstrap fallbacks.
        # Lets callers detect a model that never tool-calls (vs. one that hiccuped).
        self.model_tool_calls = 0
        self.bootstrap_used = False
        # Set when the step cap was hit before the model returned a final message,
        # so callers can distinguish "ran out of budget" from "finished cleanly".
        self.hit_max_steps = False
        # Number of model iterations actually consumed this run. Lets a multi-phase
        # caller (e.g. run_prove) enforce a single global step budget across loops.
        self.steps_run = 0

        from opentorus.research.tasks import get_task

        planned_task = get_task(self.ot_dir, self._task_id) if self._task_id else None

        result_text = "Reached the maximum number of steps without a final answer."
        stop_decision: PolicyDecision | None = None
        tool_parse_retries = 0
        # The provider said the request does not fit its context window: compact the
        # session once (forced) and ask again; a second overflow in the run is raised.
        context_overflow_compacted = False
        deliverable_retries = 0
        # Consecutive replies cut off at the output-token limit (reset by a complete one).
        length_continuations = 0
        recovery_hint: str | None = None
        run_started = time.monotonic()
        # ``max_steps = inf`` means truly unbounded: run until the deliverable is
        # done, the no-progress stall guard trips, or the user interrupts (Ctrl-C).
        # A finite max_steps is a hard cap.
        for _ in StepCapPolicy(self.max_steps).steps():
            self.steps_run += 1
            self._runner.step = self.steps_run
            self._emit(TurnStarted(step=self.steps_run, session_id=self.session_id))
            # External cancellation (a campaign engine pausing, a caller's Ctrl-C proxy):
            # honoured before spending anything on this step.
            cancel = self._runner.check_cancel()
            if cancel is not None:
                result_text = self._stop_run(cancel)
                stop_decision = cancel
                break
            # Hard budget gate: stop cleanly before spending more on the next turn.
            budget = GovernanceBudgetPolicy(self.ot_dir, self.config, self.session_id).check()
            if budget is not None:
                self._append(SessionMessage(role="assistant", content=budget.message))
                result_text = budget.message
                stop_decision = budget
                self._emit_stop(budget)
                break
            wall = self._wall_clock_decision(run_started)
            if wall is not None:
                result_text = self._stop_run(wall)
                stop_decision = wall
                break
            stall = self._policies.before_turn(self._context(run_started))
            if stall.stops:
                result_text = self._stop_run(stall)
                stop_decision = stall
                break
            # A background job that finished since the last turn is announced (and
            # recorded), so the model never has to poll or sleep for it.
            for notice in drain_notices(self.registry):
                self._append(SessionMessage(role="user", content=f"[OpenTorus notice] {notice}"))
            messages = build_messages(
                self.root,
                self.ot_dir,
                self.config,
                self.registry.names(),
                planned_task=planned_task,
                recovery_hint=recovery_hint,
                goal=task,
                provider=self.provider,
                history_session_id=self.session_id if self.isolate_history else None,
                reported_prompt_tokens=self._last_prompt_tokens,
                token_scale=self._token_scale,
            )
            recovery_hint = None
            tool_choice: str | dict | None = None
            if (
                self._deliverable.needs_deliverable(planned_task)
                and not self._session_ready()
                and deliverable_retries > 0
                and self._provider_kind() == "ollama"
            ):
                tool_choice = "required"
            try:
                # Pre-egress DLP runs first: never send secrets/PII to a cloud provider
                # (no-op for a local/mock provider, whose payload does not leave the
                # machine). Then the provider turn, then the usage ledger.
                turn = self._runner.request(messages, tool_choice=tool_choice)
                self._calibrate_tokens(messages, turn.response)
            except ContextLengthExceededError:
                if not context_overflow_compacted and self._compact_after_overflow():
                    context_overflow_compacted = True
                    continue
                raise
            except ProviderError as exc:
                if tool_parse_retries < _MAX_TOOL_PARSE_RETRIES and is_recoverable_tool_parse_error(
                    exc
                ):
                    tool_parse_retries += 1
                    self._append(SessionMessage(role="user", content=TOOL_PARSE_RECOVERY))
                    continue
                raise
            if turn.stop is not None:
                self._append(SessionMessage(role="assistant", content=turn.stop.message))
                result_text = turn.stop.message
                stop_decision = turn.stop
                self._emit_stop(turn.stop)
                break
            response = turn.response
            assert response is not None  # request() returns a response or a stop

            if response.truncated:
                # The reply stopped at the output-token limit: it is incomplete. Keep
                # its text, drop its tool calls WITHOUT executing them (a cut-off call
                # can carry cut-off arguments — half a file, half a command), and ask
                # for the rest. A cut-off message is never accepted as the final answer.
                limit_stop = self._handle_truncated(response, length_continuations)
                if limit_stop is not None:
                    result_text = self._stop_run(limit_stop)
                    stop_decision = limit_stop
                    break
                length_continuations += 1
                continue
            length_continuations = 0

            if response.kind == "message":
                # Stall backstop: a model that keeps answering in chat (no tool call)
                # makes no progress. The bootstrap below resets this streak when it
                # actually runs a tool; during gap-fill the bootstrap does not re-fire,
                # so without this the loop would cycle to the step ceiling. Break early
                # on a repeated identical reply once a sketch already exists.
                chat_stall = self._chat_only.note_message(
                    response.content,
                    in_gap_fill=self._deliverable.in_gap_fill(),
                    tool_calls_this_run=self.tool_calls_this_run,
                )
                if chat_stall is not None:
                    if response.content.strip():
                        self._append(SessionMessage(role="assistant", content=response.content))
                    result_text = chat_stall.message
                    stop_decision = chat_stall
                    _logger.info("%s", result_text)
                    self._emit_stop(chat_stall)
                    break
                missing_deliverable = (
                    self._deliverable.needs_deliverable(planned_task) and not self._session_ready()
                )
                if missing_deliverable:
                    if deliverable_retries < _MAX_DELIVERABLE_RETRIES:
                        deliverable_retries += 1
                        if response.content.strip():
                            self._append(SessionMessage(role="assistant", content=response.content))
                        recovery_hint = self._deliverable.recovery_hint(
                            planned_task, deliverable_retries, self.tool_calls_this_run
                        )
                        continue
                    boot = self._deliverable.bootstrap_call(planned_task, self.root, self.ot_dir)
                    if boot is not None:
                        name, args = boot
                        if self.registry.get(name) is not None:
                            self.bootstrap_used = True
                            call_id = uuid.uuid4().hex
                            self._append(
                                SessionMessage(
                                    role="assistant",
                                    content="(bootstrap: model did not call tools)",
                                    metadata={
                                        "tool_calls": [{"id": call_id, "name": name, "args": args}]
                                    },
                                )
                            )
                            self._status("tool", name)
                            content = self._run_tool(name, args, call_id)
                            self._append(
                                SessionMessage(
                                    role="tool",
                                    content=content,
                                    metadata={
                                        "tool_call_id": call_id,
                                        "name": name,
                                        "ok": self._last_tool_ok,
                                    },
                                )
                            )
                            failure_stop = self._tracker.stop_decision()
                            if failure_stop is not None:
                                result_text = self._stop_run(failure_stop)
                                stop_decision = failure_stop
                                break
                            self._chat_only.reset()  # a tool ran → progress
                            continue
                    elif self._deliverable.in_gap_fill():
                        if response.content.strip():
                            self._append(SessionMessage(role="assistant", content=response.content))
                        recovery_hint = self._deliverable.gap_fill_hint()
                        continue
                # The <memory_citations> block is bookkeeping, not part of the answer:
                # record which memory entries were used (once per session), then strip it.
                from opentorus.research.memory_index import take_citations

                final_text = take_citations(
                    self.ot_dir, self.config, response.content, self.session_id
                )
                self._append(SessionMessage(role="assistant", content=final_text))
                result_text = final_text
                break

            # The model may request several tool calls in one turn; execute each
            # in order, every one independently permission-gated and logged.
            resolved = [
                (c.tool_name or "", c.tool_args or {}, c.tool_call_id or uuid.uuid4().hex)
                for c in response.iter_tool_calls()
            ]
            self.model_tool_calls += len(resolved)

            # Persist one assistant turn listing every tool call, so the provider
            # can correlate the tool results that follow on the next iteration.
            self._append(
                SessionMessage(
                    role="assistant",
                    content=response.content,
                    metadata={
                        "tool_calls": [
                            {"id": cid, "name": nm, "args": ar} for nm, ar, cid in resolved
                        ]
                    },
                )
            )

            cancelled: PolicyDecision | None = None
            for index, (nm, ar, cid) in enumerate(resolved):
                cancelled = self._runner.check_cancel()
                if cancelled is not None:
                    # Every call from here on was never dispatched: say so explicitly,
                    # so the persisted turn pairs every call with an honest result.
                    self._record_unrun(resolved[index:], interrupted=None)
                    break
                self._status("tool", nm)
                try:
                    content = self._run_tool(nm, ar, cid)
                except BaseException:
                    # Ctrl-C (or any abort) while this tool was running: whether its
                    # effect happened is unknown; the calls after it never ran. An abort
                    # before dispatch (e.g. at the confirmation prompt) did not run it.
                    dispatched = getattr(self._runner, "dispatched_call_id", None) == cid
                    self._record_unrun(resolved[index:], interrupted=cid if dispatched else None)
                    raise
                self._append(
                    SessionMessage(
                        role="tool",
                        content=content,
                        metadata={"tool_call_id": cid, "name": nm, "ok": self._last_tool_ok},
                    )
                )
            if cancelled is not None:
                result_text = self._stop_run(cancelled)
                stop_decision = cancelled
                break
            failure_stop = self._tracker.stop_decision()
            if failure_stop is not None:
                result_text = self._stop_run(failure_stop)
                stop_decision = failure_stop
                break
            self._chat_only.reset()  # a tool ran → progress
        else:
            self.hit_max_steps = True
            self._append(SessionMessage(role="assistant", content=result_text))
            stop_decision = PolicyDecision(
                action=PolicyAction.STOP,
                reason_code=ReasonCode.STEP_CAP_REACHED,
                message=result_text,
            )
            self._emit_stop(stop_decision)

        if stop_decision is None:
            self._emit_stop(
                PolicyDecision(
                    action=PolicyAction.ALLOW, reason_code=ReasonCode.OK, message=result_text
                )
            )
        self._log_usage_total()
        self._record_patch(task)
        from opentorus.notifications import notify_turn_complete

        notify_turn_complete(
            self.config.ui,
            summary=result_text,
            elapsed_seconds=time.monotonic() - run_started,
            task=task,
        )
        return result_text

    def _compact_after_overflow(self) -> bool:
        """Force one session compaction after a context-length rejection."""
        from opentorus.agent.compaction import maybe_compact_session

        _logger.info("The request exceeded the model's context window; compacting once.")
        try:
            return maybe_compact_session(
                self.ot_dir,
                self.config,
                provider=self.provider,
                reported_prompt_tokens=self._last_prompt_tokens,
                token_scale=self._token_scale,
                force=True,
            )
        except OpenTorusError as exc:
            _logger.debug("Forced compaction failed: %s", exc)
            return False

    def _calibrate_tokens(
        self, messages: list[SessionMessage], response: ProviderResponse | None
    ) -> None:
        """Remember the provider's prompt-token count and its ratio to our estimate."""
        usage = getattr(response, "usage", None) if response is not None else None
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage is not None else 0
        if prompt <= 0:
            return
        import json

        from opentorus.agent.compaction import estimate_tokens, total_tokens

        try:
            specs = json.dumps(self.registry.specs(), default=str)
        except (TypeError, ValueError):
            specs = ""
        estimate = total_tokens(messages) + (estimate_tokens(specs) if specs else 0)
        self._last_prompt_tokens = prompt
        self._token_scale = prompt / estimate if estimate > 0 else None

    def _record_unrun(self, calls: list[tuple[str, dict, str]], *, interrupted: str | None) -> None:
        """Persist an explicit result for each call of a batch that did not complete.

        ``interrupted`` is the id of the call that was running when the run was
        aborted (its outcome is unknown); every other call listed was cancelled
        before dispatch and did not run. Nothing is executed here, and a later
        rebuild/replay of the session reads these results instead of guessing.
        """
        for name, _args, call_id in calls:
            running = call_id == interrupted
            self._append(
                SessionMessage(
                    role="tool",
                    content=TOOL_OUTCOME_UNKNOWN if running else TOOL_NOT_EXECUTED,
                    metadata={
                        "tool_call_id": call_id,
                        "name": name,
                        "ok": False,
                        "unrun": "interrupted_while_running" if running else "not_dispatched",
                    },
                )
            )

    def _handle_truncated(
        self, response: ProviderResponse, continuations: int
    ) -> PolicyDecision | None:
        """Record a length-truncated reply; return a stop once continuations run out.

        The partial text is persisted as an assistant turn (with a placeholder when it
        is empty, so the history keeps alternating roles) and marked ``truncated``; the
        names of the dropped tool calls are kept in its metadata for the audit trail,
        but never as ``tool_calls`` — no result will follow them. Unless the bounded
        number of continuations is spent, a continuation request is appended as the
        next user turn and ``None`` is returned so the loop asks again.
        """
        dropped = [c.tool_name or "" for c in response.iter_tool_calls()]
        text = response.content or ""
        if not text.strip():
            text = "(reply cut off at the output-token limit before any text)"
        self._append(
            SessionMessage(
                role="assistant",
                content=text,
                metadata={"truncated": True, "dropped_tool_calls": dropped},
            )
        )
        cap = max(0, int(getattr(self.config.agent, "max_length_continuations", 3)))
        if dropped:
            _logger.info(
                "Reply hit the output-token limit; %d tool call(s) dropped unexecuted: %s",
                len(dropped),
                ", ".join(dropped),
            )
        if continuations < cap:
            self._append(
                SessionMessage(
                    role="user",
                    content=LENGTH_CONTINUATION,
                    metadata={"synthetic": "length_continuation"},
                )
            )
            return None
        return PolicyDecision(
            action=PolicyAction.STOP,
            reason_code=ReasonCode.OUTPUT_TRUNCATED,
            message=(
                "[stopped] The model's reply was cut off at the output-token limit"
                + (f" and {cap} continuation request(s) did not complete it" if cap else "")
                + ". Its incomplete tool calls were not executed and the cut-off text was "
                "not accepted as an answer. Raise model.max_tokens (model.num_predict for "
                "Ollama), or ask for a smaller step."
            ),
            metadata={"dropped_tool_calls": dropped, "continuations": continuations},
        )

    def _wall_clock_decision(self, run_started: float) -> PolicyDecision | None:
        limit = self.config.agent.max_wall_seconds
        if limit is None or limit <= 0:
            return None
        return WallClockPolicy(limit).check(time.monotonic() - run_started, self.steps_run)

    def _log_usage_total(self) -> None:
        """Log the run's cumulative input/output tokens and estimated cost."""
        from opentorus.usage import format_usage_total, summarize_usage

        try:
            summary = summarize_usage(self.ot_dir, self.session_id)
        except OpenTorusError as exc:
            _logger.debug("Failed to summarize usage for session %s: %s", self.session_id, exc)
            return
        if summary.turns:
            _logger.info("%s", format_usage_total(summary))

    def _record_patch(self, task: str) -> None:
        """Record this run's file edits as an applied patch artifact (no git commit)."""
        if not self._pending_edits:
            return
        from opentorus.research.patches import FileChange, record_applied_patch

        changes = [
            FileChange(
                path=path,
                old_content=old,
                new_content=new,
                is_new=(old == "" and new != ""),
            )
            for path, old, new in self._pending_edits
        ]
        try:
            record_applied_patch(self.ot_dir, changes, reason=task, task_id=self._task_id)
        except OpenTorusError as exc:
            _logger.debug("Failed to record applied patch: %s", exc)
        self._pending_edits = []
