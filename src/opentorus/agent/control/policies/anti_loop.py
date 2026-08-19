"""Anti-loop guards: pure state machines behind the agent loop's circling backstops.

Every guard here was calibrated on recorded runs and speaks to the model in a fixed
prose message; the messages are the contract (pinned by
``tests/test_control_plane_characterization.py``). What changed in the extraction is
only *where* the state lives: each guard is a small object the loop owns and delegates
to, so a campaign worker can compose the same guards without inheriting the loop.

The thresholds keep their historical names (``_MAX_IDENTICAL_FAILURES`` and friends)
because tests import them by name from ``opentorus.agent.loop``, which re-exports them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from opentorus.agent.control.models import PolicyAction, PolicyDecision, ReasonCode

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

# The two chat-only stall messages. Which one a run gets depends on whether the model
# ever called a tool: never at all points at missing tool-calling support.
NO_TOOL_CALLS_STOP = (
    "Stopped: the model produced no tool calls at all despite tools being available — it "
    "likely does not support tool calling, which OpenTorus requires. Configure a "
    "tool-calling model (e.g. a recent OpenAI/Claude chat model, or `ollama pull qwen3`)."
)
KEPT_CHATTING_STOP = (
    "Stopped: the model kept replying in chat without calling tools (no further progress). "
    "The dossier holds the current state."
)


def stable_error_key(text: str) -> str:
    """Strip per-call noise so the same error keys the same way twice."""
    for pattern, placeholder in _VOLATILE_IN_ERRORS:
        text = pattern.sub(placeholder, text)
    return text


def tool_sig(name: str, args: dict) -> str:
    """The (tool, arguments) signature every repeat/failure guard keys on."""
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


def _stop(reason: ReasonCode, message: str, **metadata: object) -> PolicyDecision:
    return PolicyDecision(
        action=PolicyAction.STOP, reason_code=reason, message=message, metadata=dict(metadata)
    )


def _warn(reason: ReasonCode, message: str, **metadata: object) -> PolicyDecision:
    return PolicyDecision(
        action=PolicyAction.WARN, reason_code=reason, message=message, metadata=dict(metadata)
    )


def _block(reason: ReasonCode, message: str, **metadata: object) -> PolicyDecision:
    return PolicyDecision(
        action=PolicyAction.BLOCK, reason_code=reason, message=message, metadata=dict(metadata)
    )


# --- identical failures ----------------------------------------------------------------


@dataclass(frozen=True)
class FailureObservation:
    """What one failing call added to the identical-failure bookkeeping."""

    key: str
    seen: int
    streak: int
    revisited: bool


class IdenticalFailureGuard:
    """Consecutive identical (tool, args, error) triples, plus run-lifetime failure memory.

    ``streak`` counts an unchanged call repeated verbatim and resets on any change or on
    a success of that same call; ``failure_counts`` remembers every distinct failure
    for the run so a model alternating between two failing calls (A, B, A, B …) is told
    it is circling even though the streak never grows.
    """

    def __init__(self) -> None:
        self.streak = 0
        self.streak_key: str | None = None
        self.streak_tool: str | None = None
        # (tool, args, error) -> how often it failed, consecutive or not. Deliberately
        # NOT reset per run: the prove loop runs several phases against one loop, and
        # a wall hit in the literature phase is still a wall in the proof phase.
        self.failure_counts: dict[str, int] = {}

    def reset_run(self) -> None:
        """Per-run reset of the streak (the failure memory deliberately survives)."""
        self.streak = 0
        self.streak_key = None
        self.streak_tool = None

    @staticmethod
    def failure_key(sig: str, content: str) -> str:
        # Normalized for the same reason as the unchanged-error key: a fresh artifact id,
        # temp path or source position in the message must not split one recurring
        # failure into a string of unique ones that no threshold can ever reach.
        return f"{sig}\n{stable_error_key(content[:2000])}"

    def observe(self, name: str, sig: str, content: str) -> FailureObservation:
        """Book one failure; says whether it is a revisit and how long the streak is."""
        key = self.failure_key(sig, content)
        # Run-lifetime memory, separate from the consecutive streak below. The streak
        # only ever held ONE key, so a model alternating between two failing calls —
        # A fails, B fails, A fails again — reset it every time and never tripped any
        # guard. Counting every distinct failure for the whole run catches that, and
        # tells the model it is circling rather than letting it rediscover the wall.
        self.failure_counts[key] = self.failure_counts.get(key, 0) + 1
        seen = self.failure_counts[key]
        revisited = seen > 1 and key != self.streak_key
        if key == self.streak_key:
            self.streak += 1
        else:
            self.streak_key = key
            self.streak = 1
            self.streak_tool = name
        return FailureObservation(key=key, seen=seen, streak=self.streak, revisited=revisited)

    @staticmethod
    def revisit_note(seen: int) -> str:
        return (
            f"\n\nYou already tried this exact call earlier in this run "
            f"({seen} times now) and it failed the same way. Repeating it cannot "
            "help. Change the arguments, use a different tool, or record the dead "
            "end with memory_add(kind=decisions) and move on."
        )

    def warn_suffix(self, name: str) -> str | None:
        """The ``[loop guard]`` countdown once the streak reached the WARN threshold."""
        if self.streak < _IDENTICAL_FAILURE_WARN:
            return None
        guard = (
            f"\n\n[loop guard] This exact {name} call has now failed {self.streak} "
            "times with the identical error. Do NOT repeat it unchanged — change the "
            "arguments to address the error above, take a different approach, or record "
            "the blocker with memory_add(kind=decisions)."
        )
        remaining = _MAX_IDENTICAL_FAILURES - self.streak
        if remaining > 0:
            guard += f" The run stops after {remaining} more identical failure(s)."
        return guard

    def annotate(self, name: str, content: str) -> str:
        suffix = self.warn_suffix(name)
        return content if suffix is None else content + suffix

    def note_failure(self, name: str, sig: str, content: str) -> tuple[str, PolicyDecision | None]:
        """Book a failure and return the annotated content plus the guard's decision.

        The decision is ``None`` below the WARN threshold, ``WARN`` while the countdown
        runs, and ``STOP`` (with the stop message) once the cap is reached.
        """
        observation = self.observe(name, sig, content)
        if observation.revisited:
            content = content + self.revisit_note(observation.seen)
        content = self.annotate(name, content)
        stop = self.stop_decision()
        if stop is not None:
            return content, stop
        suffix = self.warn_suffix(name)
        if suffix is not None:
            return content, _warn(
                ReasonCode.REPEATED_IDENTICAL_FAILURE, suffix, streak=self.streak, tool=name
            )
        return content, None

    def note_success(self, sig: str) -> None:
        """Reset the streak when the streaking call finally succeeds.

        A success of a *different* tool does not reset it: a model that interleaves
        harmless status polls with the same doomed call is still stuck.
        """
        if self.streak_key is not None and self.streak_key.startswith(f"{sig}\n"):
            self.streak = 0
            self.streak_key = None
            self.streak_tool = None

    def stop_message(self) -> str | None:
        if self.streak < _MAX_IDENTICAL_FAILURES:
            return None
        return (
            f"Stopped: {self.streak_tool} failed {self.streak} times with "
            "identical arguments and an identical error — no progress is possible without "
            "changing the call. The failing call and its error are preserved in the "
            "session log; the dossier holds the current state."
        )

    def stop_decision(self) -> PolicyDecision | None:
        message = self.stop_message()
        if message is None:
            return None
        return _stop(
            ReasonCode.REPEATED_IDENTICAL_FAILURE,
            message,
            streak=self.streak,
            tool=self.streak_tool,
        )


# --- one error surviving changing arguments -------------------------------------------


class UnchangedErrorGuard:
    """Warn, then stop, when new arguments keep producing the *same* error.

    Both other guards key on the whole (tool, args, error) triple, so a model that
    rewrites its arguments each time never repeats one and slips past both — while
    making the identical mistake. Found by the run digest on two recorded runs:
    36 proof_write failures across 26 distinct argument sets, 11 of which returned
    one and the same "PAPER-0001 does not contain a numbered result 2.2". The model
    was busily editing the proof body and never touched the citation that was wrong.

    The key is normalized first (see :func:`stable_error_key`): a verifier stamps every
    rejection with a fresh proof id, a fresh temp path and a shifting source position,
    which otherwise made two reports of one error look like two errors and left this
    guard dead on exactly the tool where circling costs the most.
    """

    def __init__(self) -> None:
        # (tool, error) -> the distinct argument sets that produced it.
        self.error_signatures: dict[str, set[str]] = {}
        self.stop: PolicyDecision | None = None
        self.last_decision: PolicyDecision | None = None

    def note(self, name: str, sig: str, content: str) -> str:
        """Record ``sig`` against the error and return the (possibly annotated) content."""
        error_key = f"{name}\n{stable_error_key(content[:2000])}"
        seen_sigs = self.error_signatures.setdefault(error_key, set())
        seen_sigs.add(sig)
        if len(seen_sigs) >= _MAX_UNCHANGED_ERROR_STOP and self.stop is None:
            self.stop = _stop(
                ReasonCode.UNCHANGED_ERROR_OUTPUT,
                f"Stopped: {name} failed {len(seen_sigs)} times with different arguments and "
                "the identical error every time — the arguments were never what was wrong, "
                "and rewriting them again cannot help. The failing calls and their error are "
                "preserved in the session log; the dossier holds the current state.",
                attempts=len(seen_sigs),
                tool=name,
            )
        if len(seen_sigs) < _MAX_UNCHANGED_ERROR_ATTEMPTS:
            self.last_decision = None
            return content
        note = (
            f"\n\nYou have now called {name} {len(seen_sigs)} times with "
            "different arguments and gotten this identical error every time. The "
            "arguments are not the problem — the error is telling you something you "
            "have not addressed yet. Read it literally and fix what it names, or record "
            "the obstruction with memory_add(kind=decisions) and take another route."
        )
        self.last_decision = _warn(
            ReasonCode.UNCHANGED_ERROR_OUTPUT, note, attempts=len(seen_sigs), tool=name
        )
        return content + note


# --- the facade the loop talks to ---------------------------------------------------


class ToolFailureTracker:
    """Every failure path of a tool call funnels through here (``note_failure``).

    Reproduces the pre-extraction ``AgentLoop._note_tool_failure`` byte for byte:
    exempt tools are left alone; a revisit gets the "already tried" note, otherwise the
    unchanged-error guard gets its say; then the identical-failure countdown is
    appended. ``last_tool_ok`` is the outcome flag compaction reads to keep failed
    attempts verbatim.
    """

    def __init__(
        self,
        *,
        identical: IdenticalFailureGuard | None = None,
        unchanged: UnchangedErrorGuard | None = None,
        exempt: frozenset[str] = _REPEAT_GUARD_EXEMPT,
    ) -> None:
        self.identical = identical or IdenticalFailureGuard()
        self.unchanged = unchanged or UnchangedErrorGuard()
        self.exempt = exempt
        self.last_tool_ok = True

    def reset_run(self) -> None:
        self.identical.reset_run()
        self.last_tool_ok = True

    def note_failure(self, name: str, sig: str, content: str) -> str:
        """Track an identical failing (tool, args, error) triple; annotate from WARN on."""
        # Every failure path in the tool runner funnels through here, so this is the one
        # place that has to mark the outcome. Compaction reads it to keep failed attempts
        # verbatim instead of reducing them to a tool name in a comma list.
        self.last_tool_ok = False
        if name in self.exempt:
            return content
        observation = self.identical.observe(name, sig, content)
        if observation.revisited:
            content = content + self.identical.revisit_note(observation.seen)
        else:
            content = self.unchanged.note(name, sig, content)
        return self.identical.annotate(name, content)

    def note_success(self, sig: str) -> None:
        self.identical.note_success(sig)

    def stop_decision(self) -> PolicyDecision | None:
        """The honest stop once either dead-end cap is reached.

        Two ladders end here. The streak counts an unchanged call repeated verbatim; the
        unchanged-error ceiling counts one error surviving ever-changing arguments, which
        the streak structurally cannot see because every new argument set resets it.
        """
        if self.unchanged.stop is not None:
            return self.unchanged.stop
        return self.identical.stop_decision()

    def stop_message(self) -> str | None:
        decision = self.stop_decision()
        return None if decision is None else decision.message


# --- repeated calls of read-only tools -------------------------------------------------


@dataclass(frozen=True)
class RepeatVerdict:
    """``allow`` (run it), ``reserve`` (answer from cache, logged ok) or ``block``."""

    kind: str
    message: str = ""
    decision: PolicyDecision | None = None

    @property
    def allowed(self) -> bool:
        return self.kind == "allow"


class RepeatCallGuard:
    """Repeat-blocking of idempotent read tools, with the bounded read-cache re-serve."""

    def __init__(self) -> None:
        self.tool_sigs_ok: set[str] = set()
        self.read_fail_paths: set[str] = set()
        # Content of successful read_file/paper_read calls, so a repeated read can be
        # re-served (its content may have been compacted out of context) instead of
        # blocked.
        self.read_cache: dict[str, str] = {}
        self.reserve_counts: dict[str, int] = {}

    def reset_run(self) -> None:
        self.tool_sigs_ok = set()
        self.read_fail_paths = set()
        self.read_cache = {}
        self.reserve_counts = {}

    def check(
        self, name: str, args: dict, sig: str, deliverable_hint: str | Callable[[], str]
    ) -> RepeatVerdict:
        """Decide before a call runs; ``deliverable_hint`` may be a callable (evaluated lazily)."""
        if name == "read_file":
            path = str(args.get("path", "")).strip()
            if path and path in self.read_fail_paths:
                message = (
                    f"Blocked repeat read_file on missing file {path}. "
                    "Use write_file with artifact IDs from status."
                )
                return RepeatVerdict(
                    "block", message, _block(ReasonCode.CACHED_SOURCE_REREAD, message, path=path)
                )
        if (
            name in _REPEAT_GUARD_TOOLS
            and name not in _REPEAT_GUARD_EXEMPT
            and sig in self.tool_sigs_ok
        ):
            deliverable = deliverable_hint() if callable(deliverable_hint) else deliverable_hint
            # read_file of a known path is idempotent retrieval, not exploration:
            # its content may have been compacted out of context, so re-serve the
            # cached content (with a nudge) rather than hard-blocking — which would
            # otherwise strand the agent, unable to recover a file it already read.
            if name in ("read_file", "paper_read") and sig in self.read_cache:
                served = self.reserve_counts.get(sig, 0) + 1
                self.reserve_counts[sig] = served
                if served <= _MAX_CACHED_RESERVES:
                    message = (
                        f"(Already read this earlier in the run; re-showing the "
                        f"cached content — then produce the deliverable: {deliverable}.)\n\n"
                        f"{self.read_cache[sig]}"
                    )
                    return RepeatVerdict(
                        "reserve",
                        message,
                        _warn(ReasonCode.CACHED_SOURCE_REREAD, message, served=served),
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
                return RepeatVerdict(
                    "block",
                    message,
                    _block(ReasonCode.CACHED_SOURCE_REREAD, message, served=served),
                )
            message = (
                f"Blocked repeat {name} with the same arguments. "
                f"Produce the deliverable now ({deliverable})."
            )
            return RepeatVerdict("block", message, _block(ReasonCode.CACHED_SOURCE_REREAD, message))
        return RepeatVerdict("allow")

    def note_result(self, name: str, args: dict, sig: str, ok: bool, content: str) -> None:
        """Remember what a call that actually ran produced."""
        if ok and name in _REPEAT_GUARD_TOOLS and name not in _REPEAT_GUARD_EXEMPT:
            self.tool_sigs_ok.add(sig)
        if name == "read_file":
            path = str(args.get("path", "")).strip()
            # Only a genuinely missing file is a "fail path"; a policy refusal of an
            # existing protected artifact must not be mislabeled "missing" (which would
            # wrongly steer the model to write_file).
            if path and content.startswith("Not a file"):
                self.read_fail_paths.add(path)
            elif ok:
                # Cache so a later repeat can be re-served instead of blocked.
                self.read_cache[sig] = content
        elif name == "paper_read" and ok:
            # Idempotent retrieval of a parsed note: cache for re-serve on repeat.
            self.read_cache[sig] = content


# --- collecting is not progress ------------------------------------------------------


class AcquisitionGuard:
    """Search streak plus acquisition/processing ratio; nudges attach to acquisition calls."""

    def __init__(self) -> None:
        # Consecutive lit_search/web_search calls without substantive work between.
        self.search_streak = 0
        # Run totals behind the acquisition/processing ratio (see _ACQUISITION_RATIO).
        self.acquisition_calls = 0
        self.processing_calls = 0

    def reset_run(self) -> None:
        self.search_streak = 0
        self.acquisition_calls = 0
        self.processing_calls = 0

    def note_tool(self, name: str) -> None:
        """Book a tool that actually ran (ok or not — a failed fetch still collected)."""
        if name in _SEARCH_STREAK_TOOLS:
            self.search_streak += 1
        elif name not in _SEARCH_STREAK_NEUTRAL:
            self.search_streak = 0
        if name in _ACQUISITION_TOOLS:
            self.acquisition_calls += 1
        elif name not in _SEARCH_STREAK_NEUTRAL:
            self.processing_calls += 1

    def nudge_decision(self, name: str) -> PolicyDecision | None:
        """Tell a collecting-but-not-reading run to stop collecting.

        Two patterns, one message. The *streak* catches the original failure mode —
        consecutive searches that fetch nothing. The *ratio* catches the one the streak
        cannot see, where a fetch between every pair of searches keeps resetting the
        counter while nothing gets read. Only attached to an acquisition call, so a run
        that has already turned to processing is never nagged.
        """
        if name not in _ACQUISITION_TOOLS:
            return None
        if name in _SEARCH_STREAK_TOOLS and self.search_streak >= _SEARCH_STREAK_WARN:
            return _warn(
                ReasonCode.SEARCH_STREAK_LIMIT,
                f"\n\n[loop guard] This is consecutive search #{self.search_streak} "
                "with nothing fetched or read in between. STOP searching: "
                "paper_fetch the most relevant hit NOW and paper_read it, or proceed "
                "to the deliverable — more searching adds no papers.",
                streak=self.search_streak,
            )
        processing = self.processing_calls
        if (
            self.acquisition_calls >= _ACQUISITION_MIN
            and self.acquisition_calls > _ACQUISITION_RATIO * max(processing, 1)
        ):
            return _warn(
                ReasonCode.LOW_ACQUISITION_RATIO,
                f"\n\n[loop guard] {self.acquisition_calls} searches/fetches so far against "
                f"{processing} calls that did anything with the results. Collecting is not "
                "progress: paper_read what you already have, then record what it gives you "
                "(memory_add, claim_new) or write the deliverable. Fetching more will not "
                "move the run forward.",
                acquisition=self.acquisition_calls,
                processing=processing,
            )
        return None

    def nudge(self, name: str) -> str | None:
        decision = self.nudge_decision(name)
        return None if decision is None else decision.message


# --- chat-only stall -------------------------------------------------------------------


class ChatOnlyStallGuard:
    """A model that keeps answering in chat (no tool call) makes no progress.

    The bootstrap resets this streak when it actually runs a tool; during gap-fill the
    bootstrap does not re-fire, so without this the loop would cycle to the step
    ceiling. A repeated identical reply once a sketch already exists ends it early.
    """

    def __init__(self) -> None:
        self.streak = 0
        self.last: str | None = None

    def reset(self) -> None:
        """A tool ran → progress."""
        self.streak = 0
        self.last = None

    def note_message(
        self, content: str, *, in_gap_fill: bool, tool_calls_this_run: int
    ) -> PolicyDecision | None:
        content_norm = (content or "").strip()
        self.streak += 1
        repeated = bool(content_norm) and content_norm == self.last
        self.last = content_norm
        if self.streak >= _MAX_CHAT_ONLY_STALL or (repeated and in_gap_fill):
            if tool_calls_this_run == 0:
                # The model never called a single tool despite tools being available —
                # a strong sign it does not support tool calling, which OpenTorus
                # requires for every deliverable.
                message = NO_TOOL_CALLS_STOP
            else:
                message = KEPT_CHATTING_STOP
            return _stop(
                ReasonCode.NO_ARTIFACT_PROGRESS,
                message,
                streak=self.streak,
                repeated=repeated,
                tool_calls_this_run=tool_calls_this_run,
            )
        return None
