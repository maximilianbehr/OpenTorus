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
from opentorus.tools.base import (
    Tool,
    ToolCall,
    coerce_tool_args,
    normalize_arg_keys,
    validate_tool_args,
)
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

# Backstop against a model that re-issues the SAME failing tool call and gets the
# SAME error back, forever. A tool call that ran but failed still counted as
# "progress" (it reset the chat-only streak), so with max_steps=inf an unwinnable
# tool rejection cycled indefinitely (observed: 60 identical proof_write rejections,
# 41 minutes, ~5M prompt tokens). From the WARN threshold on, the error is annotated
# with an explicit do-not-repeat instruction; at the stop threshold the run ends
# honestly. Streak = consecutive identical (tool, args, error) triples; any change
# to the call, a different error, or a success of that call resets it.
_IDENTICAL_FAILURE_WARN = 3
_MAX_IDENTICAL_FAILURES = 6
# Distinct argument sets that may produce one identical error before the model is told
# the arguments are not what is wrong. Calibrated on the recorded runs: the two
# pathological ones reach 11 and 9, every healthy one reaches 1.
_MAX_UNCHANGED_ERROR_ATTEMPTS = 4
# …and a ceiling, because the warning alone changed nothing. A prove run rewrote its
# run_shell command 20 times and got the identical "not available during prove" block
# every time; the nudge fired from the fourth on and the model kept going for another
# sixteen turns. The consecutive-failure ladder cannot stop this — the arguments differ,
# so its streak resets on every call. Calibrated across 19 recorded workspaces: the
# median run reaches 1 distinct argument set per error, only three exceed 6 (at 20, 11
# and 9), so 8 stops every pathological run without touching a healthy one.
_MAX_UNCHANGED_ERROR_STOP = 8

# Tokens the *system* mints per call, which make two reports of one and the same error
# look like two different errors. A verifier rejection carries a fresh artifact id, a
# fresh temp path, and a source position that shifts by a line whenever the model edits
# anything — so keying the unchanged-error guard on the raw text made it structurally
# unable to fire for proof_submit. Observed: 20 Coq rejections in one run, 11 of them
# the identical `Syntax error: '.' expected after [command]`, and not one guard.
# Only the guard's *key* is normalized; the model still sees the verbatim message.
_VOLATILE_IN_ERRORS = (
    (re.compile(r"(?:/private)?/(?:tmp|var/folders)/[^\s\"',;)]+"), "<tmp>"),
    (
        re.compile(r"\b(?:PROOF|EXP|CLAIM|EVID|PAPER|SRC|FIG|DATASET|REPO|TASK|ACTION)-\d+\b"),
        "<id>",
    ),
    (re.compile(r"\bline \d+, characters \d+-\d+"), "line <n>, characters <n>"),
    (re.compile(r"\b(?:line|Line)s? \d+(?:-\d+)?"), "line <n>"),
    (re.compile(r":\d+:\d+(?=:|\b)"), ":<n>:<n>"),
)


def _stable_error_key(text: str) -> str:
    """Strip per-call noise so the same error keys the same way twice."""
    for pattern, placeholder in _VOLATILE_IN_ERRORS:
        text = pattern.sub(placeholder, text)
    return text


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
# ``status`` is also never repeat-blocked: it reports the live inventory the agent
# legitimately re-polls after writing artifacts, so it is re-run, not hard-blocked.
_REPEAT_GUARD_EXEMPT = frozenset({"lit_search", "paper_fetch", "paper_list", "status"})

_REPEAT_GUARD_TOOLS = frozenset({"glob_files", "read_file", "list_files", "status", "paper_read"})

# A re-read of an already-read path is served from the read cache and logged ok=True,
# so that a compacted-away file can be recovered. That makes it look like progress to
# every other guard: the chat-only streak resets, and neither failure tracker sees it
# because nothing failed. It was also unbounded — two runs re-read one and the same
# statement.md 24 and 25 times, burning a full model round-trip each time while doing
# nothing. Half of the recorded workspaces (12 of 24) exceed three repeats; the ordinary
# ones stop at five calls, the pathological ones run to 25. So the first few re-serves
# stay, and past that the call fails instead — which finally feeds the identical-failure
# tracker and ends the run honestly.
_MAX_CACHED_RESERVES = 4

# Search-spam nudge: three real runs died in a loop of consecutive lit_search /
# web_search calls that never fetched or read anything (11 searches in one run).
# Search tools are rightly exempt from the repeat guards (results change), so from
# the WARN threshold on, each further consecutive search carries an explicit
# stop-searching instruction. Any substantive tool resets the streak; inventory
# polls (paper_list/status/memory_list) are neutral.
_SEARCH_STREAK_TOOLS = frozenset({"lit_search", "web_search"})
_SEARCH_STREAK_NEUTRAL = frozenset({"paper_list", "status", "memory_list"})
_SEARCH_STREAK_WARN = 4

# The streak alone measures the wrong thing. A run that goes
# search, search, fetch, search, search, fetch … resets the counter on every fetch and
# never trips it, while doing nothing with what it collects. Observed in a real run
# (marcus-de-oliveira): 115 actions — 39 web_search, 33 lit_search, 31 paper_fetch, but
# only 5 paper_read and zero proof_write. It was stopped by the no-progress window, not
# by this guard. paper_fetch is acquisition, not processing: it puts a file on disk and
# tells the model nothing.
#
# So the ratio is tracked as well: acquisition against everything substantive that is
# not acquisition. Processing is deliberately the complement rather than a list, so a
# newly added tool counts as work by default instead of silently inflating the ratio.
_ACQUISITION_TOOLS = frozenset({"lit_search", "web_search", "paper_fetch", "fetch_url"})
# Calibrated against twelve recorded runs rather than guessed. Their end-of-run ratios
# separate cleanly: the pathological run sits at 21.2x, every healthy one between 0.2x
# and 1.6x — so 4.0 has a wide margin on both sides. The minimum matters just as much:
# at 12 the check also fires on three healthy runs, because early literature work is
# legitimately acquisition-heavy before anything has been read. At 15 it fires on
# exactly one run of the twelve, the one that collected 106 items and read 5.
_ACQUISITION_MIN = 15
_ACQUISITION_RATIO = 4.0


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
        stall_check: Callable[[], str | None] | None = None,
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
        # State that must be usable before (and across) run(). The streak counters
        # below are deliberately reset per run(); these are not.
        self.steps_run = 0
        self._last_tool_ok = True
        self._fail_streak = 0
        self._fail_streak_key: str | None = None
        self._fail_streak_tool: str | None = None
        self._search_streak = 0
        self._acquisition_calls = 0
        self._processing_calls = 0
        # (tool, error) -> the distinct argument sets that produced it. Catches a model
        # that keeps changing the call without addressing what the error actually says.
        self._error_signatures: dict[str, set[str]] = {}
        self._unchanged_error_stop: str | None = None
        # (tool, args, error) -> how often it failed, consecutive or not. Deliberately
        # NOT reset per run(): the prove loop runs several phases against one loop, and
        # a wall hit in the literature phase is still a wall in the proof phase.
        self._failure_counts: dict[str, int] = {}
        # Optional caller-supplied stall detector, probed once per step like the
        # budget gate. Returning a message ends the run honestly with that text —
        # the seam that lets a phase without a deliverable yet (e.g. the prove
        # draft phase) enforce its own no-progress window even when caps are inf.
        self._stall_check = stall_check
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
        # Identical-failure backstop state — see _MAX_IDENTICAL_FAILURES. Declared in
        # __init__ (so the object is usable before run()); reset here per run.
        self._fail_streak = 0
        self._last_tool_ok = True
        self._fail_streak_key = None
        self._fail_streak_tool = None
        # Consecutive lit_search/web_search calls without substantive work between.
        self._search_streak = 0
        # Run totals behind the acquisition/processing ratio (see _ACQUISITION_RATIO).
        self._acquisition_calls = 0
        self._processing_calls = 0
        # Content of successful read_file calls, so a repeated read can be re-served
        # (its content may have been compacted out of context) instead of blocked.
        self._read_cache: dict[str, str] = {}
        self._reserve_counts: dict[str, int] = {}
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
            # Hard budget gate: stop cleanly before spending more on the next turn.
            budget_stop = self._budget_stop()
            if budget_stop is not None:
                self._append(SessionMessage(role="assistant", content=budget_stop))
                result_text = budget_stop
                break
            wall_stop = self._wall_clock_stop(run_started)
            if wall_stop is not None:
                self._append(SessionMessage(role="assistant", content=wall_stop))
                result_text = wall_stop
                _logger.info("%s", wall_stop)
                break
            stall_stop = self._stall_check() if self._stall_check is not None else None
            if stall_stop is not None:
                self._append(SessionMessage(role="assistant", content=stall_stop))
                result_text = stall_stop
                _logger.info("%s", stall_stop)
                break
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
            # Pre-egress DLP: never send secrets/PII to a cloud provider (no-op for a
            # local/mock provider, whose payload does not leave the machine).
            egress_stop = self._screen_outbound(messages)
            if egress_stop is not None:
                self._append(SessionMessage(role="assistant", content=egress_stop))
                result_text = egress_stop
                break
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
                    if self.tool_calls_this_run == 0:
                        # The model never called a single tool despite tools being
                        # available — a strong sign it does not support tool calling,
                        # which OpenTorus requires for every deliverable.
                        result_text = (
                            "Stopped: the model produced no tool calls at all despite tools "
                            "being available — it likely does not support tool calling, which "
                            "OpenTorus requires. Configure a tool-calling model (e.g. a recent "
                            "OpenAI/Claude chat model, or `ollama pull qwen3`)."
                        )
                    else:
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
                                    metadata={
                                        "tool_call_id": call_id,
                                        "name": name,
                                        "ok": self._last_tool_ok,
                                    },
                                )
                            )
                            failure_stop = self._identical_failure_stop()
                            if failure_stop is not None:
                                self._append(SessionMessage(role="assistant", content=failure_stop))
                                result_text = failure_stop
                                _logger.info("%s", failure_stop)
                                break
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
                        metadata={"tool_call_id": cid, "name": nm, "ok": self._last_tool_ok},
                    )
                )
            failure_stop = self._identical_failure_stop()
            if failure_stop is not None:
                self._append(SessionMessage(role="assistant", content=failure_stop))
                result_text = failure_stop
                _logger.info("%s", failure_stop)
                break
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

    def _note_tool_success(self, sig: str) -> None:
        """Reset the identical-failure streak when the streaking call finally succeeds.

        A success of a *different* tool does not reset it: a model that interleaves
        harmless status polls with the same doomed call is still stuck.
        """
        if self._fail_streak_key is not None and self._fail_streak_key.startswith(f"{sig}\n"):
            self._fail_streak = 0
            self._fail_streak_key = None
            self._fail_streak_tool = None

    def _note_unchanged_error(self, name: str, sig: str, content: str) -> str:
        """Warn when new arguments keep producing the *same* error.

        Both other guards key on the whole (tool, args, error) triple, so a model that
        rewrites its arguments each time never repeats one and slips past both — while
        making the identical mistake. Found by the run digest on two recorded runs:
        36 proof_write failures across 26 distinct argument sets, 11 of which returned
        one and the same "PAPER-0001 does not contain a numbered result 2.2". The model
        was busily editing the proof body and never touched the citation that was wrong.

        Threshold calibrated against the recorded runs: the two pathological ones reach
        11 and 9 distinct argument sets per error, every healthy run reaches 1.

        The key is normalized first (see ``_stable_error_key``): a verifier stamps every
        rejection with a fresh proof id, a fresh temp path and a shifting source
        position, which otherwise made two reports of one error look like two errors and
        left this guard dead on exactly the tool where circling costs the most.
        """
        error_key = f"{name}\n{_stable_error_key(content[:2000])}"
        seen_sigs = self._error_signatures.setdefault(error_key, set())
        seen_sigs.add(sig)
        if len(seen_sigs) >= _MAX_UNCHANGED_ERROR_STOP and self._unchanged_error_stop is None:
            self._unchanged_error_stop = (
                f"Stopped: {name} failed {len(seen_sigs)} times with different arguments and "
                "the identical error every time — the arguments were never what was wrong, "
                "and rewriting them again cannot help. The failing calls and their error are "
                "preserved in the session log; the dossier holds the current state."
            )
        if len(seen_sigs) < _MAX_UNCHANGED_ERROR_ATTEMPTS:
            return content
        return (
            f"{content}\n\nYou have now called {name} {len(seen_sigs)} times with "
            "different arguments and gotten this identical error every time. The "
            "arguments are not the problem — the error is telling you something you "
            "have not addressed yet. Read it literally and fix what it names, or record "
            "the obstruction with memory_add(kind=decisions) and take another route."
        )

    def _acquisition_nudge(self, name: str) -> str | None:
        """Tell a collecting-but-not-reading run to stop collecting.

        Two patterns, one message. The *streak* catches the original failure mode —
        consecutive searches that fetch nothing. The *ratio* catches the one the streak
        cannot see, where a fetch between every pair of searches keeps resetting the
        counter while nothing gets read. Only attached to an acquisition call, so a run
        that has already turned to processing is never nagged.
        """
        if name not in _ACQUISITION_TOOLS:
            return None
        if name in _SEARCH_STREAK_TOOLS and self._search_streak >= _SEARCH_STREAK_WARN:
            return (
                f"\n\n[loop guard] This is consecutive search #{self._search_streak} "
                "with nothing fetched or read in between. STOP searching: "
                "paper_fetch the most relevant hit NOW and paper_read it, or proceed "
                "to the deliverable — more searching adds no papers."
            )
        processing = self._processing_calls
        if (
            self._acquisition_calls >= _ACQUISITION_MIN
            and self._acquisition_calls > _ACQUISITION_RATIO * max(processing, 1)
        ):
            return (
                f"\n\n[loop guard] {self._acquisition_calls} searches/fetches so far against "
                f"{processing} calls that did anything with the results. Collecting is not "
                "progress: paper_read what you already have, then record what it gives you "
                "(memory_add, claim_new) or write the deliverable. Fetching more will not "
                "move the run forward."
            )
        return None

    def _note_tool_failure(self, name: str, sig: str, content: str) -> str:
        """Track an identical failing (tool, args, error) triple; annotate from WARN on."""
        # Every failure path in _run_tool funnels through here, so this is the one place
        # that has to mark the outcome. Compaction reads it to keep failed attempts
        # verbatim instead of reducing them to a tool name in a comma list.
        self._last_tool_ok = False
        if name in _REPEAT_GUARD_EXEMPT:
            return content
        # Normalized for the same reason as the unchanged-error key: a fresh artifact id,
        # temp path or source position in the message must not split one recurring
        # failure into a string of unique ones that no threshold can ever reach.
        key = f"{sig}\n{_stable_error_key(content[:2000])}"
        # Run-lifetime memory, separate from the consecutive streak below. The streak
        # only ever held ONE key, so a model alternating between two failing calls —
        # A fails, B fails, A fails again — reset it every time and never tripped any
        # guard. Counting every distinct failure for the whole run catches that, and
        # tells the model it is circling rather than letting it rediscover the wall.
        self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
        seen = self._failure_counts[key]
        revisited = seen > 1 and key != self._fail_streak_key
        if key == self._fail_streak_key:
            self._fail_streak += 1
        else:
            self._fail_streak_key = key
            self._fail_streak = 1
            self._fail_streak_tool = name
        if revisited:
            content = (
                f"{content}\n\nYou already tried this exact call earlier in this run "
                f"({seen} times now) and it failed the same way. Repeating it cannot "
                "help. Change the arguments, use a different tool, or record the dead "
                "end with memory_add(kind=decisions) and move on."
            )
        else:
            content = self._note_unchanged_error(name, sig, content)
        if self._fail_streak < _IDENTICAL_FAILURE_WARN:
            return content
        guard = (
            f"\n\n[loop guard] This exact {name} call has now failed {self._fail_streak} "
            "times with the identical error. Do NOT repeat it unchanged — change the "
            "arguments to address the error above, take a different approach, or record "
            "the blocker with memory_add(kind=decisions)."
        )
        remaining = _MAX_IDENTICAL_FAILURES - self._fail_streak
        if remaining > 0:
            guard += f" The run stops after {remaining} more identical failure(s)."
        return content + guard

    def _identical_failure_stop(self) -> str | None:
        """Return an honest stop message once either dead-end cap is reached.

        Two ladders end here. The streak counts an unchanged call repeated verbatim; the
        unchanged-error ceiling counts one error surviving ever-changing arguments, which
        the streak structurally cannot see because every new argument set resets it.
        """
        if self._unchanged_error_stop is not None:
            return self._unchanged_error_stop
        if self._fail_streak < _MAX_IDENTICAL_FAILURES:
            return None
        return (
            f"Stopped: {self._fail_streak_tool} failed {self._fail_streak} times with "
            "identical arguments and an identical error — no progress is possible without "
            "changing the call. The failing call and its error are preserved in the "
            "session log; the dossier holds the current state."
        )

    def _wall_clock_stop(self, run_started: float) -> str | None:
        """Stop once the run has spent its wall-clock budget.

        Every other guard — the chat-only streak, the identical-failure cap, the
        no-progress windows — assumes turns come back. A single model call that hangs
        satisfies none of them, and with ``max_steps: inf`` a run can repeat that
        indefinitely; only the provider timeout ends each individual call. This is the
        one bound that holds regardless of what the model does, so it is checked before
        spending on the next turn rather than in the middle of one.
        """
        limit = self.config.agent.max_wall_seconds
        if limit is None or limit <= 0:
            return None
        elapsed = time.monotonic() - run_started
        if elapsed < limit:
            return None
        return (
            f"Stopped: this run reached its wall-clock budget of {limit:.0f}s "
            f"(elapsed {elapsed:.0f}s) after {self.steps_run} model steps. Everything "
            "recorded so far is preserved; re-run to continue from the artifacts, or "
            "raise agent.max_wall_seconds."
        )

    def _budget_stop(self) -> str | None:
        """Return a stop message if a configured budget cap is reached, else None."""
        from opentorus.governance import BudgetExceeded, assert_within_budget

        try:
            assert_within_budget(self.ot_dir, self.config, session_id=self.session_id)
        except BudgetExceeded as exc:
            return f"[stopped] {exc}"
        return None

    def _screen_outbound(self, messages) -> str | None:  # noqa: ANN001
        """Pre-egress DLP: block a cloud send that would leak secrets/PII (else None).

        A local/mock provider never leaves the machine, so it is exempt; cloud sends
        are screened when ``governance.dlp`` is enabled and fail closed.
        """
        import json

        from opentorus.usage import is_local_provider

        if not self.config.governance.dlp:
            return None
        if is_local_provider(getattr(self.provider, "name", "unknown"), self.config.model.base_url):
            return None
        from opentorus.governance import DlpBlocked, assert_egress_safe

        try:
            payload = json.dumps(messages, default=str)
        except (TypeError, ValueError):
            payload = str(messages)
        try:
            assert_egress_safe(payload, self.config)
        except DlpBlocked as exc:
            return (
                f"[stopped] Pre-egress DLP blocked the request: {exc} Remove the secret/PII "
                "from the conversation, or disable governance.dlp to override."
            )
        return None

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
        base_url = self.config.model.base_url
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
                    cost_usd=estimate_cost(
                        provider_name, model, prompt_tokens, completion_tokens, base_url
                    ),
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
                base_url=base_url,
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
        # The signature is computed up front so EVERY rejection path below can feed
        # the identical-failure tracker: a model hammering the same blocked call is
        # exactly as stuck as one hammering a failing tool (forensics of the
        # perfect-mirsky run found blocked/empty paths invisible to all guards).
        # A model that writes "read_ file" meant read_file — no registered tool has
        # whitespace in its name — so resolve before anything else keys on the name.
        tool, name = self.registry.resolve(name)
        sig = _tool_sig(name, args)
        self._last_tool_ok = True
        if tool is None:
            log_action(self.ot_dir, name, ok=False, args=args, stderr_summary="unknown tool")
            available = ", ".join(sorted(self.registry.names()))
            return self._note_tool_failure(
                name,
                sig,
                f"Unknown tool: '{name}'. It does not exist — do not call it again. "
                f"Available tools: {available}. "
                "To search files use glob_files/list_files; to read use read_file.",
            )

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
                return self._note_tool_failure(name, sig, blocked)

        if name == "read_file":
            path = str(args.get("path", "")).strip()
            if path and path in self._read_fail_paths:
                message = (
                    f"Blocked repeat read_file on missing file {path}. "
                    "Use write_file with artifact IDs from status."
                )
                log_action(self.ot_dir, name, ok=False, args=args, stderr_summary=message[:500])
                return self._note_tool_failure(name, sig, message)
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
                served = self._reserve_counts.get(sig, 0) + 1
                self._reserve_counts[sig] = served
                if served <= _MAX_CACHED_RESERVES:
                    log_action(
                        self.ot_dir,
                        name,
                        ok=True,
                        args=args,
                        stdout_summary="(re-served from read cache)",
                    )
                    return (
                        f"(Already read this earlier in the run; re-showing the "
                        f"cached content — then produce the deliverable: {deliverable}.)\n\n"
                        f"{self._read_cache[sig]}"
                    )
                # Deliberately free of a per-call counter: a number that ticks up would
                # make every one of these look like a new error and blind the very
                # streak guard that is supposed to end the loop.
                message = (
                    f"{name} with these arguments has already been re-served from cache "
                    "several times and the content has not changed. Re-reading it cannot "
                    f"move this run forward: produce the deliverable ({deliverable}), or "
                    "if something is missing, get it with a different call."
                )
                log_action(self.ot_dir, name, ok=False, args=args, stderr_summary=message[:500])
                return self._note_tool_failure(name, sig, message)
            message = (
                f"Blocked repeat {name} with the same arguments. "
                f"Produce the deliverable now ({deliverable})."
            )
            log_action(self.ot_dir, name, ok=False, args=args, stderr_summary=message[:500])
            return self._note_tool_failure(name, sig, message)

        # A model that JSON-encodes an argument one time too many sent the right value,
        # only wrapped in a string. Re-read those before validating — the rejection text
        # alone did not help: llama3.1:70b repeated the same mistake sixteen times with
        # the required shape spelled out in every reply.
        schema = getattr(tool, "input_schema", {}) or {}
        # Repair split argument *names* before values: an unknown key passes
        # validation silently and the argument simply never arrives.
        args = normalize_arg_keys(schema, args)
        args = coerce_tool_args(schema, args)
        schema_error = validate_tool_args(schema, args)
        if schema_error is not None:
            message = f"Invalid arguments for {name}: {schema_error}"
            log_action(self.ot_dir, name, ok=False, args=args, stderr_summary=message[:500])
            return self._note_tool_failure(name, sig, message)

        decision = self._evaluate(tool, args)
        if decision is not None:
            blocked = self._enforce(name, args, decision)
            if blocked is not None:
                return self._note_tool_failure(name, sig, blocked)

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
            return self._note_tool_failure(name, sig, message)
        self._last_tool_ok = result.ok
        self.tool_calls_this_run += 1
        self.tools_used_this_run.append(name)
        if name in _SEARCH_STREAK_TOOLS:
            self._search_streak += 1
        elif name not in _SEARCH_STREAK_NEUTRAL:
            self._search_streak = 0
        if name in _ACQUISITION_TOOLS:
            self._acquisition_calls += 1
        elif name not in _SEARCH_STREAK_NEUTRAL:
            self._processing_calls += 1
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
                    # The gate detail names the current parsed-paper count, so the
                    # failure key only stays identical while literature makes zero
                    # progress — exactly when repeating proof_write is truly stuck.
                    return self._note_tool_failure(name, sig, blocked)
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
        if result.ok:
            self._note_tool_success(sig)
            nudge = self._acquisition_nudge(name)
            if nudge is not None:
                return result.content + nudge
            return result.content
        return self._note_tool_failure(name, sig, result.content)

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
