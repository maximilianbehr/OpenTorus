"""The minimal agent loop.

The loop is provider-agnostic: it persists the user turn, asks the provider for
the next action, and either returns a message or routes a tool call through the
registry. Tool results are appended to the session and logged as actions. A step
cap prevents runaway loops.
"""

from __future__ import annotations

import itertools
import json
import logging
import math
import re
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from opentorus.actions import log_action
from opentorus.agent.context import build_messages
from opentorus.agent.prompts import TOOL_PARSE_RECOVERY
from opentorus.agent.session import SessionMessage, append_message
from opentorus.agent.task_bootstrap import bootstrap_tool_for_task, recovery_hint_for_task
from opentorus.approvals import EXTERNAL_SESSION_KEY
from opentorus.config import Config, OperatingStyle
from opentorus.errors import OpenTorusError, ProviderError, is_recoverable_tool_parse_error
from opentorus.permissions.policy import (
    PermissionDecision,
    evaluate_command,
    evaluate_external_tool,
    evaluate_write,
)
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.tools.base import Tool, ToolCall, validate_tool_args
from opentorus.tools.registry import ToolRegistry

# A confirmation callback receives the decision, a human-readable description
# of the pending action, and an optional session scope (e.g. "external" for all
# network tools). Returns True to allow it.
ConfirmCallback = Callable[[PermissionDecision, str, str | None], bool]

_logger = logging.getLogger(__name__)

_MAX_TOOL_PARSE_RETRIES = 3
_MAX_DELIVERABLE_RETRIES = 5
# Backstop against a model that keeps replying in prose instead of calling tools
# (common with reasoning models). After this many consecutive chat-only turns with
# no tool executed, stop instead of cycling to the step ceiling — important during
# gap-fill, where the deliverable bootstrap does not re-fire and caps may be inf.
_MAX_CHAT_ONLY_STALL = 8

_PROVE_RECOVERY_HINT = (
    "This prove session requires a deliverable tool call — not a chat reply. "
    "Call proof_write(problem_id=…, scope=primary) with theorem restating the dossier, "
    "main_proof, and [GAP-n] markers."
)

_PROVE_GAPS_RECOVERY_HINT = (
    "Primary proof_write exists but recorded gap(s) remain — this prove run is NOT complete. "
    "Read the latest PROOF-* and relevant PAPER-* notes; use paper_read, lit_search, "
    "paper_fetch, or exp_run as needed; then proof_write(scope=primary) to fill [GAP-n] "
    "or shrink the gap list. Do NOT reply with a summary until gaps are closed or you "
    "document a blocker in memory_add(kind=decisions)."
)

_PROVE_RECOVERY_HINT_AFTER_TOOLS = (
    "This prove session is NOT complete. You used other tools but a primary proof_write "
    "is still mandatory. Call proof_write(scope=primary): restate the dossier in "
    "`theorem`, then main_proof with [GAP-n]. "
    "Speculative side threads (e.g. Fredholm, alternative formulations) belong in "
    "scope=exploration with connection_to_dossier — they do NOT finish the run alone. "
    "claim_new, and evidence_add alone do not finish a prove run."
)

_LIT_RECOVERY_HINT = (
    "Literature phase requires tool calls — not a chat reply. "
    "Read the problem statement, run one lit_search with its technical terms only, "
    "then paper_fetch directly relevant hits. Do NOT call proof_write yet."
)

_LIT_RECOVERY_HINT_AFTER_TOOLS = (
    "Literature phase is NOT complete. "
    "Use lit_search, paper_fetch, and paper_read as needed; "
    "when papers are [parsed], add memory_add(kind=observations) with PAPER-* refs. "
    "Do NOT call proof_write or end with a summary yet."
)

# Literature search/fetch tools are never repeat-blocked — their results can change,
# so only the step budget limits usage. paper_read is NOT exempt: reading an
# already-parsed note is idempotent, so a repeat is re-served from cache (see below).
_REPEAT_GUARD_EXEMPT = frozenset({"lit_search", "paper_fetch", "paper_list"})

_REPEAT_GUARD_TOOLS = frozenset({"glob_files", "read_file", "list_files", "status", "paper_read"})


def _tool_sig(name: str, args: dict) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


# A status callback reports what the loop is doing so the UI can show progress.
# ``phase`` is "model" (the model is deciding) or "tool" (a tool is running);
# ``detail`` carries the tool name for the "tool" phase.
StatusCallback = Callable[[str, str | None], None]
LLMRequestCallback = Callable[[list[SessionMessage], list[dict] | None], None]
LLMResponseCallback = Callable[["ProviderResponse"], None]

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
    ) -> None:
        self.root = root
        self.ot_dir = ot_dir
        self.provider = provider
        self.registry = registry
        self.config = config
        self.max_steps = max_steps
        self.session_id = session_id or uuid.uuid4().hex
        self.confirm = confirm
        self.on_text = on_text
        self.on_status = on_status
        self.on_llm_request = on_llm_request
        self.on_llm_response = on_llm_response
        self.stream_llm = stream_llm
        self.on_thinking = on_thinking
        self.deliverable_bootstrap = deliverable_bootstrap
        self.session_gate = session_gate
        self._session_recovery_hint = session_recovery_hint
        self._pre_deliverable_gate = pre_deliverable_gate
        self._pre_deliverable_gate_detail = pre_deliverable_gate_detail
        self._deliverable_complete = deliverable_complete
        self._tool_gate = tool_gate
        self._required_deliverable_tool = (
            deliverable_bootstrap[0] if deliverable_bootstrap is not None else None
        )
        self._deliverable_satisfied = False
        # Set when a write/command tool runs successfully, so callers know the
        # workspace may have changed and verification is warranted.
        self.edited = False
        # Accumulated (path, old_content, new_content) for file edits the agent
        # made, recorded as a patch artifact at the end of the run.
        self._pending_edits: list[tuple[str, str, str]] = []
        self._task_id: str | None = None
        self.tool_calls_this_run: int = 0
        self.tools_used_this_run: list[str] = []

    @property
    def _style(self) -> OperatingStyle:
        return self.config.agent.style

    @property
    def _review(self) -> bool:
        return self.config.agent.mode == "review"

    def _append(self, message: SessionMessage) -> None:
        message.metadata.setdefault("session_id", self.session_id)
        append_message(self.ot_dir, message)

    def _status(self, phase: str, detail: str | None = None) -> None:
        if self.on_status is not None:
            self.on_status(phase, detail)

    def _session_ready(self) -> bool:
        if self._deliverable_satisfied:
            if self._deliverable_complete is not None and not self._deliverable_complete():
                return False
            return True
        if self.session_gate is not None and self.session_gate():
            return True
        return False

    def run(self, task: str) -> str:
        """Run one task to completion and return the final assistant message."""
        self._append(SessionMessage(role="user", content=task))
        self._pending_edits = []
        self.tool_calls_this_run = 0
        self.tools_used_this_run = []
        self._tool_sigs_ok: set[str] = set()
        self._read_fail_paths: set[str] = set()
        # Content of successful read_file calls, so a repeated read can be re-served
        # (its content may have been compacted out of context) instead of blocked.
        self._read_cache: dict[str, str] = {}
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
        tool_parse_retries = 0
        deliverable_retries = 0
        recovery_hint: str | None = None
        chat_only_streak = 0
        last_chat_only: str | None = None
        run_started = time.monotonic()
        # ``max_steps = inf`` means truly unbounded: run until the deliverable is
        # done, the no-progress stall guard trips, or the user interrupts (Ctrl-C).
        # A finite max_steps is a hard cap.
        step_iter: Iterable[int] = (
            itertools.count() if math.isinf(self.max_steps) else range(int(self.max_steps))
        )
        for _ in step_iter:
            self.steps_run += 1
            messages = build_messages(
                self.root,
                self.ot_dir,
                self.config,
                self.registry.names(),
                planned_task=planned_task,
                recovery_hint=recovery_hint,
                goal=task,
                provider=self.provider,
            )
            recovery_hint = None
            self._status("model")
            started = time.monotonic()
            tool_choice: str | dict | None = None
            if (
                (
                    planned_task is not None
                    or self.deliverable_bootstrap is not None
                    or self.session_gate is not None
                )
                and not self._session_ready()
                and deliverable_retries > 0
                and self.config.model.provider == "ollama"
            ):
                tool_choice = "required"
            try:
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
            except ProviderError as exc:
                if tool_parse_retries < _MAX_TOOL_PARSE_RETRIES and is_recoverable_tool_parse_error(
                    exc
                ):
                    tool_parse_retries += 1
                    self._append(SessionMessage(role="user", content=TOOL_PARSE_RECOVERY))
                    continue
                raise
            self._record_usage(messages, response, time.monotonic() - started)

            if response.kind == "message":
                # Stall backstop: a model that keeps answering in chat (no tool call)
                # makes no progress. The bootstrap below resets this streak when it
                # actually runs a tool; during gap-fill the bootstrap does not re-fire,
                # so without this the loop would cycle to the step ceiling. Break early
                # on a repeated identical reply once a sketch already exists.
                content_norm = (response.content or "").strip()
                in_gap_fill = (
                    self._deliverable_satisfied
                    and self._deliverable_complete is not None
                    and not self._deliverable_complete()
                )
                chat_only_streak += 1
                repeated = bool(content_norm) and content_norm == last_chat_only
                last_chat_only = content_norm
                if chat_only_streak >= _MAX_CHAT_ONLY_STALL or (repeated and in_gap_fill):
                    if response.content.strip():
                        self._append(SessionMessage(role="assistant", content=response.content))
                    result_text = (
                        "Stopped: the model kept replying in chat without calling tools "
                        "(no further progress). The dossier holds the current state."
                    )
                    _logger.info("%s", result_text)
                    break
                needs_deliverable = (
                    planned_task is not None
                    or self.deliverable_bootstrap is not None
                    or self.session_gate is not None
                )
                missing_deliverable = needs_deliverable and not self._session_ready()
                if missing_deliverable:
                    if deliverable_retries < _MAX_DELIVERABLE_RETRIES:
                        deliverable_retries += 1
                        if response.content.strip():
                            self._append(SessionMessage(role="assistant", content=response.content))
                        if planned_task is not None:
                            recovery_hint = recovery_hint_for_task(
                                planned_task, attempt=deliverable_retries
                            )
                        elif self.session_gate is not None:
                            if self._session_recovery_hint is not None:
                                recovery_hint = self._session_recovery_hint()
                            elif self.tool_calls_this_run > 0:
                                recovery_hint = _LIT_RECOVERY_HINT_AFTER_TOOLS
                            else:
                                recovery_hint = _LIT_RECOVERY_HINT
                        elif (
                            self._deliverable_satisfied
                            and self._deliverable_complete is not None
                            and not self._deliverable_complete()
                        ):
                            if self._session_recovery_hint is not None:
                                recovery_hint = self._session_recovery_hint()
                            else:
                                recovery_hint = _PROVE_GAPS_RECOVERY_HINT
                        elif self.tool_calls_this_run > 0:
                            recovery_hint = _PROVE_RECOVERY_HINT_AFTER_TOOLS
                        else:
                            recovery_hint = _PROVE_RECOVERY_HINT
                        continue
                    boot = None
                    if planned_task is not None:
                        boot = bootstrap_tool_for_task(planned_task, self.root, self.ot_dir)
                    elif self.deliverable_bootstrap is not None:
                        gap_fill_in_progress = (
                            self._deliverable_satisfied
                            and self._deliverable_complete is not None
                            and not self._deliverable_complete()
                        )
                        if not gap_fill_in_progress:
                            boot = self.deliverable_bootstrap
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
                                    metadata={"tool_call_id": call_id, "name": name},
                                )
                            )
                            chat_only_streak = 0  # a tool ran → progress
                            last_chat_only = None
                            continue
                    elif (
                        self._deliverable_satisfied
                        and self._deliverable_complete is not None
                        and not self._deliverable_complete()
                    ):
                        if response.content.strip():
                            self._append(SessionMessage(role="assistant", content=response.content))
                        if self._session_recovery_hint is not None:
                            recovery_hint = self._session_recovery_hint()
                        else:
                            recovery_hint = _PROVE_GAPS_RECOVERY_HINT
                        continue
                self._append(SessionMessage(role="assistant", content=response.content))
                result_text = response.content
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

            for nm, ar, cid in resolved:
                self._status("tool", nm)
                content = self._run_tool(nm, ar, cid)
                self._append(
                    SessionMessage(
                        role="tool",
                        content=content,
                        metadata={"tool_call_id": cid, "name": nm},
                    )
                )
            chat_only_streak = 0  # a tool ran → progress
            last_chat_only = None
        else:
            self.hit_max_steps = True
            self._append(SessionMessage(role="assistant", content=result_text))

        self._log_usage_total()
        self._record_patch(task)
        from opentorus.notifications import notify_turn_complete

        notify_turn_complete(
            self.config.ui,
            summary=result_text,
            elapsed_seconds=time.monotonic() - run_started,
        )
        return result_text

    def _record_usage(self, messages, response, elapsed: float) -> None:
        """Record a usage/cost entry for one provider turn.

        Prefers the provider's exact token counts (``response.usage``); falls back
        to a local character-count estimate when the provider does not report them
        (e.g. the offline mock).
        """
        from opentorus.agent.compaction import estimate_tokens, total_tokens
        from opentorus.usage import UsageRecord, estimate_cost, format_usage_line, record_usage

        provider_name = getattr(self.provider, "name", "unknown")
        model = self.config.model.name
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
        try:
            record_usage(
                self.ot_dir,
                UsageRecord(
                    session_id=self.session_id,
                    provider=provider_name,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    thinking_tokens=thinking_tokens,
                    latency_ms=round(elapsed * 1000),
                    cost_usd=estimate_cost(provider_name, model, prompt_tokens, completion_tokens),
                    tokens_estimated=tokens_estimated,
                ),
            )
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
            ),
        )

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

    def _evaluate(self, tool: Tool, args: dict) -> PermissionDecision | None:
        """Return a permission decision for a write/command tool, or None for reads."""
        mode = self.config.permissions.mode
        if tool.permission == "write":
            return evaluate_write(
                args.get("path", ""), mode, style=self._style, review=self._review
            )
        if tool.permission == "command":
            return evaluate_command(
                args.get("command", ""), mode, style=self._style, review=self._review
            )
        if tool.permission == "external":
            return evaluate_external_tool(tool.name, mode, style=self._style, review=self._review)
        return None

    def _run_tool(self, name: str, args: dict, call_id: str) -> str:
        tool = self.registry.get(name)
        if tool is None:
            log_action(self.ot_dir, name, ok=False, args=args, stderr_summary="unknown tool")
            return f"Unknown tool: {name}"

        if self._tool_gate is not None:
            blocked = self._tool_gate(name, args)
            if blocked is not None:
                log_action(
                    self.ot_dir,
                    name,
                    ok=False,
                    args=args,
                    stderr_summary=blocked[:500],
                )
                return blocked

        sig = _tool_sig(name, args)
        if name == "read_file":
            path = str(args.get("path", "")).strip()
            if path and path in self._read_fail_paths:
                return (
                    f"Blocked repeat read_file on missing file {path}. "
                    "Use write_file with artifact IDs from status."
                )
        if (
            name in _REPEAT_GUARD_TOOLS
            and name not in _REPEAT_GUARD_EXEMPT
            and sig in self._tool_sigs_ok
        ):
            if self._required_deliverable_tool:
                # e.g. a prove run's deliverable is proof_write, not write_file —
                # nudging toward write_file misdirects the agent during gap-fill.
                deliverable = self._required_deliverable_tool
            elif self._task_id:
                from opentorus.research.tasks import get_task

                task = get_task(self.ot_dir, self._task_id)
                deliverable = (
                    "write_file(path='analysis.md', …)"
                    if task is not None and task.category == "report"
                    else "write_file (e.g. analysis.md)"
                )
            else:
                deliverable = "write_file (e.g. analysis.md)"
            # read_file of a known path is idempotent retrieval, not exploration:
            # its content may have been compacted out of context, so re-serve the
            # cached content (with a nudge) rather than hard-blocking — which would
            # otherwise strand the agent, unable to recover a file it already read.
            if name in ("read_file", "paper_read") and sig in self._read_cache:
                return (
                    f"(Already read this earlier in the run; re-showing the "
                    f"cached content — then produce the deliverable: {deliverable}.)\n\n"
                    f"{self._read_cache[sig]}"
                )
            return (
                f"Blocked repeat {name} with the same arguments. "
                f"Produce the deliverable now ({deliverable})."
            )

        schema_error = validate_tool_args(getattr(tool, "input_schema", {}) or {}, args)
        if schema_error is not None:
            message = f"Invalid arguments for {name}: {schema_error}"
            log_action(self.ot_dir, name, ok=False, args=args, stderr_summary=message[:500])
            return message

        decision = self._evaluate(tool, args)
        if decision is not None:
            blocked = self._enforce(name, args, decision)
            if blocked is not None:
                return blocked

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
            return message
        self.tool_calls_this_run += 1
        self.tools_used_this_run.append(name)
        if result.ok and name in _REPEAT_GUARD_TOOLS and name not in _REPEAT_GUARD_EXEMPT:
            self._tool_sigs_ok.add(sig)
        if name == "read_file":
            path = str(args.get("path", "")).strip()
            # Only a genuinely missing file is a "fail path"; a policy refusal of an
            # existing protected artifact must not be mislabeled "missing" (which would
            # wrongly steer the model to write_file).
            if path and result.content.startswith("Not a file"):
                self._read_fail_paths.add(path)
            elif result.ok:
                # Cache so a later repeat can be re-served instead of blocked.
                self._read_cache[sig] = result.content
        elif name == "paper_read" and result.ok:
            # Idempotent retrieval of a parsed note: cache for re-serve on repeat.
            self._read_cache[sig] = result.content
        if result.ok and tool.permission == "write":
            self.edited = True
        elif result.ok and name in ("exp_run", "exp_new", "proof_write"):
            self.edited = True
            if (
                self._required_deliverable_tool is not None
                and name == self._required_deliverable_tool
            ):
                if self._pre_deliverable_gate is not None and not self._pre_deliverable_gate():
                    detail = (
                        self._pre_deliverable_gate_detail().strip()
                        if self._pre_deliverable_gate_detail is not None
                        else "Preconditions not met."
                    )
                    blocked = (
                        f"Blocked proof_write: literature requirements not met ({detail}). "
                        "Complete lit_search, paper_fetch, and memory_add "
                        "(one observation per parsed paper) before drafting a proof."
                    )
                    log_action(
                        self.ot_dir,
                        name,
                        ok=False,
                        args=args,
                        permission_decision=decision.model_dump() if decision else None,
                        stderr_summary=blocked[:500],
                    )
                    return blocked
                if result.metadata.get("scope", "primary") == "primary":
                    self._deliverable_satisfied = True
        elif result.ok and tool.permission == "command":
            command = str(args.get("command", ""))
            if _shell_command_likely_edits(command):
                self.edited = True
        if result.ok and is_file_edit:
            new_content = self._read_path(args["path"]) or ""
            self._pending_edits.append((args["path"], old_content or "", new_content))
        log_action(
            self.ot_dir,
            name,
            ok=result.ok,
            args=args,
            permission_decision=decision.model_dump() if decision else None,
            stdout_summary=result.content[:500] if result.ok else None,
            stderr_summary=None if result.ok else result.content[:500],
        )
        return result.content

    def _enforce(self, name: str, args: dict, decision: PermissionDecision) -> str | None:
        """Apply a permission decision. Returns a message if the call must not run."""
        if not decision.allowed:
            log_action(
                self.ot_dir,
                name,
                ok=False,
                args=args,
                permission_decision=decision.model_dump(),
                stderr_summary=decision.reason,
            )
            return f"Blocked: {decision.reason}"
        if decision.requires_confirmation:
            description = args.get("command") or args.get("path") or name
            tool = self.registry.get(name)
            is_external = tool is not None and tool.permission == "external"
            scope = EXTERNAL_SESSION_KEY if is_external else None
            approved = self.confirm(decision, str(description), scope) if self.confirm else False
            if not approved:
                log_action(
                    self.ot_dir,
                    name,
                    ok=False,
                    args=args,
                    permission_decision=decision.model_dump(),
                    stderr_summary="not confirmed",
                )
                return f"Not run (requires confirmation): {decision.reason}"
        return None
