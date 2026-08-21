"""The turn runner: one provider turn, one tool execution — with every side effect.

``AgentLoop.run()`` decides *what* happens next; the runner does the two things that
touch the outside world — asking the provider (pre-egress DLP, usage ledger, event
sink) and executing a tool call (resolution, gates, repeat guards, schema repair,
permissions, the tool itself, the action log, the failure trackers). Splitting them
lets a campaign worker drive tools and turns through the same code path as ``run``
and ``prove`` without inheriting the loop's control flow.

Byte-for-byte contract: ``execute_tool`` is the former ``AgentLoop._run_tool`` with
its ``log_action`` calls in the identical order and with identical texts; ``request``
is the former provider turn plus ``_record_usage``. Both are pinned by
``tests/test_control_plane_characterization.py``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from opentorus.actions import log_action
from opentorus.agent.control.events import RunEvent, RunEventSink, ToolExecuted, TurnCompleted
from opentorus.agent.control.models import (
    PolicyAction,
    PolicyDecision,
    ReasonCode,
    RoutingProvenance,
    ToolOutcome,
)
from opentorus.agent.control.policies.anti_loop import (
    _SEARCH_STREAK_NEUTRAL,
    AcquisitionGuard,
    RepeatCallGuard,
    ToolFailureTracker,
    tool_sig,
)
from opentorus.agent.control.policies.budget import CancellationPolicy
from opentorus.agent.control.policies.deliverables import DeliverablePolicy
from opentorus.agent.control.policies.permissions import (
    ConfirmCallback,
    enforce_permission,
    evaluate_permission,
)
from opentorus.agent.control.workflow import WorkflowPolicySet
from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.errors import OpenTorusError
from opentorus.permissions.policy import PermissionDecision
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.tools.base import (
    Tool,
    ToolCall,
    coerce_tool_args,
    normalize_arg_keys,
    validate_tool_args,
)
from opentorus.tools.registry import ToolRegistry

_logger = logging.getLogger(__name__)

# A status callback reports what the loop is doing so the UI can show progress.
# ``phase`` is "model" (the model is deciding) or "tool" (a tool is running);
# ``detail`` carries the tool name for the "tool" phase.
StatusCallback = Callable[[str, str | None], None]
LLMRequestCallback = Callable[[list[SessionMessage], list[dict] | None], None]
LLMResponseCallback = Callable[[ProviderResponse], None]

_SHELL_EDIT = re.compile(
    r"(?<![\w-])(?:>|>>|tee|mv|cp|rm|mkdir|touch|chmod|install|make|cargo)\b",
    re.I,
)


def _shell_command_likely_edits(command: str) -> bool:
    """Heuristic: does a run_shell argv likely modify the workspace?"""
    cmd = command.strip()
    if not cmd:
        return False
    if _SHELL_EDIT.search(cmd):
        return True
    if re.match(r"python(?:3)?\s+\S+", cmd):
        return True
    if re.match(r"bash\s+\S+", cmd):
        return True
    return False


# The three tools whose success means the workspace changed even though they are
# not "write" tools: they create experiment/proof artifacts under .opentorus/.
_ARTIFACT_WRITING_TOOLS = ("exp_run", "exp_new", "proof_write")


@dataclass
class TurnResult:
    """What ``request`` came back with: a response, or the decision that stopped it."""

    response: ProviderResponse | None
    stop: PolicyDecision | None = None
    elapsed: float = 0.0


class TurnRunner:
    """Executes provider turns and tool calls for one session; owns the run counters."""

    def __init__(
        self,
        root: Path,
        ot_dir: Path,
        provider: BaseProvider,
        registry: ToolRegistry,
        config: Config,
        *,
        session_id: str,
        confirm: ConfirmCallback | None = None,
        on_text: Callable[[str], None] | None = None,
        on_status: StatusCallback | None = None,
        on_llm_request: LLMRequestCallback | None = None,
        on_llm_response: LLMResponseCallback | None = None,
        stream_llm: bool = False,
        on_thinking: Callable[[str], None] | None = None,
        policies: WorkflowPolicySet | None = None,
        deliverable: DeliverablePolicy | None = None,
        repeat_guard: RepeatCallGuard | None = None,
        failure_tracker: ToolFailureTracker | None = None,
        acquisition_guard: AcquisitionGuard | None = None,
        event_sink: RunEventSink | None = None,
        routing: RoutingProvenance | None = None,
        usage_tags: dict[str, str] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.root = root
        self.ot_dir = ot_dir
        self.provider = provider
        self.registry = registry
        self.config = config
        self.session_id = session_id
        self.confirm = confirm
        self.on_text = on_text
        self.on_status = on_status
        self.on_llm_request = on_llm_request
        self.on_llm_response = on_llm_response
        self.stream_llm = stream_llm
        self.on_thinking = on_thinking
        self.policies = policies
        self.deliverable = deliverable
        self.repeat_guard = repeat_guard or RepeatCallGuard()
        self.failure_tracker = failure_tracker or ToolFailureTracker()
        self.acquisition_guard = acquisition_guard or AcquisitionGuard()
        self.event_sink = event_sink
        self.routing = routing
        self.usage_tags = dict(usage_tags or {})
        self.cancellation = CancellationPolicy(should_stop)
        # Run counters the loop exposes; reset per run by ``reset_run``.
        self.tool_calls_this_run = 0
        self.tools_used_this_run: list[str] = []
        # Set when a write/command tool runs successfully, so callers know the
        # workspace may have changed and verification is warranted. Deliberately not
        # reset per run (it answers "did this loop ever edit").
        self.edited = False
        # Accumulated (path, old_content, new_content) for file edits the agent
        # made, recorded as a patch artifact at the end of the run.
        self.pending_edits: list[tuple[str, str, str]] = []
        # The planned task (if any) whose category shapes the repeat-guard nudge.
        self.planned_task_id: str | None = None
        self.step = 0

    # --- small helpers -----------------------------------------------------------------

    def _status(self, phase: str, detail: str | None = None) -> None:
        if self.on_status is not None:
            self.on_status(phase, detail)

    def _emit(self, event: RunEvent) -> None:
        """Hand an event to the sink; a misbehaving sink must never abort the loop.

        ``events.RunEventSink`` documents that a sink never raises, but the loop is
        the one paying if it does (a lost final answer, a session left mid-turn), so
        the guarantee is enforced here rather than trusted.
        """
        if self.event_sink is None:
            return
        try:
            self.event_sink.emit(event)
        except Exception as exc:  # noqa: BLE001 — a sink must never abort the loop
            _logger.debug("Event sink raised on %s: %s", type(event).__name__, exc)

    def _provider_base_url(self) -> str | None:
        """The endpoint the provider in use actually talks to.

        A routed lease is built from a *profile*, so the provider carries its own
        ``config`` (see ``BaseProvider.config``); the workspace ``config.model`` is
        the default profile and may point elsewhere (a local vLLM while the lease is
        OpenAI, or vice versa). Locality — which decides the DLP exemption and the
        ``$0 (local)`` pricing — must follow the provider that sends the bytes. A
        provider without a config (mock, test doubles) falls back to ``config.model``.
        """
        provider_cfg = getattr(getattr(self.provider, "config", None), "model", None)
        if provider_cfg is not None:
            return getattr(provider_cfg, "base_url", None)
        return self.config.model.base_url

    def reset_run(self) -> None:
        """Per-run reset of counters and the per-run guard state."""
        self.tool_calls_this_run = 0
        self.tools_used_this_run = []
        self.pending_edits = []
        self.repeat_guard.reset_run()
        self.failure_tracker.reset_run()
        self.acquisition_guard.reset_run()

    @property
    def last_tool_ok(self) -> bool:
        return self.failure_tracker.last_tool_ok

    def check_cancel(self) -> PolicyDecision | None:
        """The caller's ``should_stop`` — consulted before a request and before a tool."""
        return self.cancellation.check()

    # --- provider turn -------------------------------------------------------------------

    def screen_outbound(self, messages: list[SessionMessage]) -> PolicyDecision | None:
        """Pre-egress DLP over a cloud send: block on secrets, redact PII (else None).

        A local/mock provider never leaves the machine, so it is exempt. For a cloud
        send, a *secret* still fails closed — that is the whole point of the control.
        PII is handled by ``governance.dlp_pii``: the default redacts it in the payload
        about to go out and lets the turn proceed. Blocking on it instead made the
        literature workflow impossible with any cloud provider (every academic PDF
        carries author emails) and pushed users toward disabling DLP altogether, which
        gives up secret protection too.

        ``messages`` is the per-turn payload and is redacted in place, so the redacted
        text is what the provider actually receives.
        """
        from opentorus.usage import is_local_provider

        if not self.config.governance.dlp:
            return None
        provider_name = getattr(self.provider, "name", "unknown")
        if is_local_provider(provider_name, self._provider_base_url()):
            return None
        from opentorus.governance import redact_pii, scan_secrets, split_findings

        mode = getattr(self.config.governance, "dlp_pii", "redact")
        try:
            payload = json.dumps(messages, default=str)
        except (TypeError, ValueError):
            payload = str(messages)
        secrets, pii = split_findings(scan_secrets(payload, scan_pii=mode != "off"))
        if secrets or (pii and mode == "block"):
            kinds = ", ".join(sorted({f.kind for f in secrets + pii}))
            fix = (
                "Remove the secret from the conversation; it must not be sent."
                if secrets
                else "Set governance.dlp_pii=redact to send with the PII removed."
            )
            return PolicyDecision(
                action=PolicyAction.STOP,
                reason_code=ReasonCode.EGRESS_BLOCKED,
                message=(f"[stopped] Pre-egress DLP blocked the request: detected {kinds}. {fix}"),
            )
        if pii and mode == "redact":
            self._redact_messages(messages, redact_pii)
        return None

    @classmethod
    def _redact_messages(cls, messages: list[SessionMessage], redact) -> None:  # noqa: ANN001
        """Rewrite message text in place so the PII never reaches the wire.

        ``content`` is not the whole payload: ``to_openai_messages`` serialises
        ``metadata["tool_calls"][i]["args"]`` into the ``arguments`` field it sends, and
        the DLP scan reads ``json.dumps(messages)`` — so redacting only ``content``
        would report PII as removed while still putting it on the wire, which is worse
        than the block it replaced. Every string in the message is rewritten, which also
        keeps the PII out of the session log this message is appended to.
        """
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                new = redact(content)
                if new != content:
                    try:
                        message.content = new
                    except (AttributeError, ValueError):  # frozen/validated model
                        pass
            metadata = getattr(message, "metadata", None)
            if isinstance(metadata, dict) and metadata:
                cls._redact_in_place(metadata, redact)

    @classmethod
    def _redact_in_place(cls, node: object, redact) -> object:  # noqa: ANN001
        """Rewrite every string inside a nested dict/list, returning the new value."""
        if isinstance(node, str):
            return redact(node)
        if isinstance(node, dict):
            for key, value in list(node.items()):
                node[key] = cls._redact_in_place(value, redact)
            return node
        if isinstance(node, list):
            for index, value in enumerate(node):
                node[index] = cls._redact_in_place(value, redact)
            return node
        return node

    def request(
        self,
        messages: list[SessionMessage],
        *,
        tool_choice: str | dict | None = None,
        screen: bool = True,
    ) -> TurnResult:
        """One provider turn: DLP screen, respond, record usage, emit ``TurnCompleted``.

        A ``ProviderError`` propagates unchanged (the loop owns the tool-parse retry);
        usage is only recorded for a turn that came back.
        """
        if screen:
            egress_stop = self.screen_outbound(messages)
            if egress_stop is not None:
                return TurnResult(response=None, stop=egress_stop)
        self._status("model")
        started = time.monotonic()
        if self.on_llm_request is not None:
            self.on_llm_request(messages, self.registry.specs())
        response = self.provider.respond(
            messages,
            tools=self.registry.specs(),
            on_text=self.on_text,
            stream=self.stream_llm,
            tool_choice=tool_choice,
            on_thinking=self.on_thinking,
        )
        if self.on_llm_response is not None:
            self.on_llm_response(response)
        elapsed = time.monotonic() - started
        self.record_usage(messages, response, elapsed)
        return TurnResult(response=response, elapsed=elapsed)

    def record_usage(
        self, messages: list[SessionMessage], response: ProviderResponse, elapsed: float
    ) -> None:
        """Record a usage/cost entry for one provider turn.

        Prefers the provider's exact token counts (``response.usage``); falls back
        to a local character-count estimate when the provider does not report them
        (e.g. the offline mock). The model column is what the provider says it is
        (``provider.model_name``) and falls back to ``config.model.name``; the model
        that actually answered (``response.model``) and the routing provenance are
        stamped when the ledger schema has the fields. Pricing follows the endpoint
        of the provider in use (a leased profile's ``base_url``), not the default
        profile's, so a routed local model is ``$0`` and a routed cloud model is not.
        """
        from opentorus.agent.compaction import estimate_tokens, total_tokens
        from opentorus.usage import UsageRecord, estimate_cost, format_usage_line
        from opentorus.usage import record_usage as append_usage_record

        provider_name = getattr(self.provider, "name", "unknown")
        model = getattr(self.provider, "model_name", None) or self.config.model.name
        actual_model = getattr(response, "model", None) or model
        base_url = self._provider_base_url()
        usage = getattr(response, "usage", None)
        thinking_tokens = 0
        if usage is not None:
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            thinking_tokens = usage.thinking_tokens
            tokens_estimated = False
        else:
            prompt_tokens = total_tokens(messages)
            # The model's output on a tool-call turn is the tool name + arguments
            # JSON, not ``content`` (which is empty there) — count it so "out" is
            # not always 0. A turn may carry several parallel tool calls; count
            # every one, not just the first scalar call.
            completion_text = response.content or ""
            for call in response.iter_tool_calls():
                completion_text += (call.tool_name or "") + json.dumps(
                    call.tool_args or {}, default=str
                )
            completion_tokens = estimate_tokens(completion_text) if completion_text else 0
            tokens_estimated = True
        cost = estimate_cost(provider_name, model, prompt_tokens, completion_tokens, base_url)
        fields: dict[str, object] = {
            "session_id": self.session_id,
            "provider": provider_name,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "thinking_tokens": thinking_tokens,
            "latency_ms": round(elapsed * 1000),
            "cost_usd": cost,
            "tokens_estimated": tokens_estimated,
        }
        # Provenance columns exist only once the routing milestone extends the ledger
        # schema; stamp what the schema knows so this works before and after.
        known = UsageRecord.model_fields
        extras: dict[str, object] = {"actual_model": actual_model}
        routing = self.routing
        if routing is not None:
            extras.update(
                {
                    "routing_decision_id": getattr(routing, "decision_id", None),
                    "task_class": getattr(routing, "task_class", None),
                    "requested_profile": getattr(routing, "requested_profile", None),
                    "selected_profile": getattr(routing, "selected_profile", None),
                    "configured_model": getattr(routing, "configured_model", None),
                    "fallback_reason": getattr(routing, "fallback_reason", None),
                }
            )
        extras.update(self.usage_tags)
        for key, value in extras.items():
            if key in known and value is not None:
                fields[key] = value
        try:
            append_usage_record(self.ot_dir, UsageRecord.model_validate(fields))
        except OpenTorusError as exc:
            _logger.debug("Failed to record usage for session %s: %s", self.session_id, exc)
        # Per-step token/cost surfaces in verbose runs via the logger.
        _logger.info(
            "%s",
            format_usage_line(
                provider_name,
                model,
                prompt_tokens,
                completion_tokens,
                thinking_tokens=thinking_tokens,
                tokens_estimated=tokens_estimated,
                base_url=base_url,
            ),
        )
        self._emit(
            TurnCompleted(
                step=self.step,
                session_id=self.session_id,
                response_kind=response.kind,
                tool_names=[c.tool_name or "" for c in response.iter_tool_calls()],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                thinking_tokens=thinking_tokens,
                tokens_estimated=tokens_estimated,
                cost_usd=cost,
                latency_ms=round(elapsed * 1000),
                provider=provider_name,
                model=model,
                actual_model=actual_model,
                routing_decision_id=(
                    getattr(routing, "decision_id", None) if routing is not None else None
                ),
            )
        )

    # --- tool execution -----------------------------------------------------------------

    def _read_path(self, user_path: str) -> str | None:
        from opentorus.paths import resolve_workspace_path

        try:
            target = resolve_workspace_path(self.root, user_path)
        except OpenTorusError:
            return None
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def evaluate(self, tool: Tool, args: dict) -> PermissionDecision | None:
        """Return a permission decision for a write/command tool, or None for reads."""
        return evaluate_permission(
            tool,
            args,
            mode=self.config.permissions.mode,
            style=self.config.agent.style,
            review=self.config.agent.mode == "review",
        )

    def enforce(self, name: str, args: dict, decision: PermissionDecision) -> str | None:
        """Apply a permission decision. Returns a message if the call must not run."""
        return enforce_permission(
            name, args, decision, ot_dir=self.ot_dir, registry=self.registry, confirm=self.confirm
        )

    def _deliverable_hint(self) -> str:
        """What the repeat guard tells the model to produce instead of re-reading."""
        if self.deliverable is not None and self.deliverable.required_tool:
            # e.g. a prove run's deliverable is proof_write, not write_file —
            # nudging toward write_file misdirects the agent during gap-fill.
            return self.deliverable.required_tool
        if self.planned_task_id:
            from opentorus.research.tasks import get_task

            task = get_task(self.ot_dir, self.planned_task_id)
            return (
                "write_file(path='analysis.md', …)"
                if task is not None and task.category == "report"
                else "write_file (e.g. analysis.md)"
            )
        return "write_file (e.g. analysis.md)"

    def _fail(
        self,
        name: str,
        args: dict,
        sig: str,
        content: str,
        *,
        blocked_by: ReasonCode | None,
        call_id: str,
        started: float,
    ) -> ToolOutcome:
        text = self.failure_tracker.note_failure(name, sig, content)
        outcome = ToolOutcome(
            name=name,
            args=args,
            ok=False,
            content=text,
            blocked_by=blocked_by,
            call_id=call_id,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        self._emit(ToolExecuted(step=self.step, session_id=self.session_id, outcome=outcome))
        return outcome

    def execute_tool(self, name: str, args: dict, call_id: str) -> ToolOutcome:
        """Run one tool call end to end; the returned ``content`` goes back to the model."""
        started = time.monotonic()
        # The signature is computed up front so EVERY rejection path below can feed
        # the identical-failure tracker: a model hammering the same blocked call is
        # exactly as stuck as one hammering a failing tool (forensics of the
        # perfect-mirsky run found blocked/empty paths invisible to all guards).
        # A model that writes "read_ file" meant read_file — no registered tool has
        # whitespace in its name — so resolve before anything else keys on the name.
        tool, name = self.registry.resolve(name)
        sig = tool_sig(name, args)
        self.failure_tracker.last_tool_ok = True
        if tool is None:
            log_action(self.ot_dir, name, ok=False, args=args, stderr_summary="unknown tool")
            available = ", ".join(sorted(self.registry.names()))
            return self._fail(
                name,
                args,
                sig,
                f"Unknown tool: '{name}'. It does not exist — do not call it again. "
                f"Available tools: {available}. "
                "To search files use glob_files/list_files; to read use read_file.",
                blocked_by=None,
                call_id=call_id,
                started=started,
            )

        if self.policies is not None:
            gate = self.policies.before_tool(name, args)
            if gate.blocks or gate.stops:
                blocked = gate.message
                log_action(
                    self.ot_dir,
                    name,
                    ok=False,
                    args=args,
                    stderr_summary=blocked[:500],
                )
                return self._fail(
                    name,
                    args,
                    sig,
                    blocked,
                    blocked_by=gate.reason_code,
                    call_id=call_id,
                    started=started,
                )

        verdict = self.repeat_guard.check(name, args, sig, self._deliverable_hint)
        if verdict.kind == "reserve":
            log_action(
                self.ot_dir,
                name,
                ok=True,
                args=args,
                stdout_summary="(re-served from read cache)",
            )
            outcome = ToolOutcome(
                name=name,
                args=args,
                ok=True,
                content=verdict.message,
                call_id=call_id,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            self._emit(ToolExecuted(step=self.step, session_id=self.session_id, outcome=outcome))
            return outcome
        if verdict.kind == "block":
            log_action(self.ot_dir, name, ok=False, args=args, stderr_summary=verdict.message[:500])
            return self._fail(
                name,
                args,
                sig,
                verdict.message,
                blocked_by=ReasonCode.CACHED_SOURCE_REREAD,
                call_id=call_id,
                started=started,
            )

        # A model that JSON-encodes an argument one time too many sent the right value,
        # only wrapped in a string. Re-read those before validating — the rejection text
        # alone did not help: llama3.1:70b repeated the same mistake sixteen times with
        # the required shape spelled out in every reply.
        schema = getattr(tool, "input_schema", {}) or {}
        # Repair split argument *names* before values: an unknown key passes
        # validation silently and the argument simply never arrives.
        repaired = normalize_arg_keys(schema, args)
        # Keep the slip visible in the ledger: the repair happens before every
        # log_action below, so recording only the fixed form would erase the signal
        # that found this defect in the first place. The note goes to the *log*, never
        # to the tool.
        log_extra = (
            {"_repaired_keys": sorted(set(args) - set(repaired))}
            if set(args) != set(repaired)
            else {}
        )
        args = coerce_tool_args(schema, repaired)
        schema_error = validate_tool_args(schema, args)
        if schema_error is not None:
            message = f"Invalid arguments for {name}: {schema_error}"
            log_action(self.ot_dir, name, ok=False, args=args, stderr_summary=message[:500])
            return self._fail(
                name, args, sig, message, blocked_by=None, call_id=call_id, started=started
            )

        decision = self.evaluate(tool, args)
        if decision is not None:
            denied = self.enforce(name, args, decision)
            if denied is not None:
                return self._fail(
                    name,
                    args,
                    sig,
                    denied,
                    blocked_by=ReasonCode.PERMISSION_DENIED,
                    call_id=call_id,
                    started=started,
                )

        is_file_edit = tool.permission == "write" and bool(args.get("path"))
        old_content = self._read_path(args["path"]) if is_file_edit else None

        call = ToolCall(id=call_id, name=name, args=args)
        try:
            result = tool.run(call)
        except Exception as exc:  # noqa: BLE001 — tool bugs must not abort the agent loop
            message = f"Tool {name} failed: {exc}"
            log_action(
                self.ot_dir,
                name,
                ok=False,
                args=args,
                permission_decision=decision.model_dump() if decision else None,
                stderr_summary=message[:500],
            )
            return self._fail(
                name, args, sig, message, blocked_by=None, call_id=call_id, started=started
            )
        self.failure_tracker.last_tool_ok = result.ok
        self.tool_calls_this_run += 1
        self.tools_used_this_run.append(name)
        self.acquisition_guard.note_tool(name)
        self.repeat_guard.note_result(name, args, sig, result.ok, result.content)
        edited = False
        if result.ok and tool.permission == "write":
            edited = True
        elif result.ok and name in _ARTIFACT_WRITING_TOOLS:
            edited = True
            if self.deliverable is not None:
                gate_block = self.deliverable.pre_gate_block(name)
                if gate_block is not None:
                    self.edited = True
                    log_action(
                        self.ot_dir,
                        name,
                        ok=False,
                        args=args,
                        permission_decision=decision.model_dump() if decision else None,
                        stderr_summary=gate_block[:500],
                    )
                    # The gate detail names the current parsed-paper count, so the
                    # failure key only stays identical while literature makes zero
                    # progress — exactly when repeating the deliverable is truly stuck.
                    return self._fail(
                        name,
                        args,
                        sig,
                        gate_block,
                        blocked_by=ReasonCode.DELIVERABLE_MISSING,
                        call_id=call_id,
                        started=started,
                    )
                self.deliverable.note_deliverable_result(name, result)
        elif result.ok and tool.permission == "command":
            command = str(args.get("command", ""))
            if _shell_command_likely_edits(command):
                edited = True
        if edited:
            self.edited = True
        file_edit: tuple[str, str, str] | None = None
        if result.ok and is_file_edit:
            new_content = self._read_path(args["path"]) or ""
            file_edit = (args["path"], old_content or "", new_content)
            self.pending_edits.append(file_edit)
        log_action(
            self.ot_dir,
            name,
            ok=result.ok,
            args={**args, **log_extra},
            permission_decision=decision.model_dump() if decision else None,
            stdout_summary=result.content[:500] if result.ok else None,
            stderr_summary=None if result.ok else result.content[:500],
        )
        if result.ok:
            self.failure_tracker.note_success(sig)
            content = result.content
            nudge = self.acquisition_guard.nudge(name)
            if nudge is not None:
                content = content + nudge
            outcome = ToolOutcome(
                name=name,
                args=args,
                ok=True,
                content=content,
                edited=edited,
                call_id=call_id,
                ran=True,
                file_edit=file_edit,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            self._emit(ToolExecuted(step=self.step, session_id=self.session_id, outcome=outcome))
            if self.policies is not None:
                self.policies.after_tool(outcome)
            return outcome
        text = self.failure_tracker.note_failure(name, sig, result.content)
        outcome = ToolOutcome(
            name=name,
            args=args,
            ok=False,
            content=text,
            call_id=call_id,
            ran=True,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        self._emit(ToolExecuted(step=self.step, session_id=self.session_id, outcome=outcome))
        if self.policies is not None:
            self.policies.after_tool(outcome)
        return outcome

    @staticmethod
    def neutral_tools() -> frozenset[str]:
        """Inventory polls that count as neither search nor processing."""
        return _SEARCH_STREAK_NEUTRAL
