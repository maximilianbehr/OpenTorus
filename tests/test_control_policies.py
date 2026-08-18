"""The control-plane policies, tested pure: thresholds, reason codes, exact strings.

The same messages are pinned end-to-end through ``AgentLoop`` in
``tests/test_control_plane_characterization.py``; here each guard is driven directly,
so a threshold or a reason code cannot drift without a test naming it.
"""

from __future__ import annotations

from enum import Enum

import pytest

from opentorus.agent.control import (
    CompositePolicySet,
    InvalidTransition,
    NullPolicySet,
    PhaseMachine,
    PolicyAction,
    PolicyContext,
    PolicyDecision,
    ReasonCode,
    ToolOutcome,
    first_blocking,
)
from opentorus.agent.control.legacy import (
    LIT_RECOVERY_HINT,
    LIT_RECOVERY_HINT_AFTER_TOOLS,
    PROVE_GAPS_RECOVERY_HINT,
    PROVE_RECOVERY_HINT,
    PROVE_RECOVERY_HINT_AFTER_TOOLS,
    LegacyCallbackPolicySet,
    pre_deliverable_block_message,
)
from opentorus.agent.control.policies import (
    AcquisitionGuard,
    CancellationPolicy,
    ChatOnlyStallGuard,
    DeliverablePolicy,
    IdenticalFailureGuard,
    NoProgressWindow,
    RepeatCallGuard,
    StepCapPolicy,
    ToolFailureTracker,
    UnchangedErrorGuard,
    WallClockPolicy,
    stable_error_key,
    tool_sig,
)
from opentorus.agent.control.policies.anti_loop import (
    _MAX_CACHED_RESERVES,
    _MAX_CHAT_ONLY_STALL,
    _MAX_IDENTICAL_FAILURES,
    _MAX_UNCHANGED_ERROR_ATTEMPTS,
    _MAX_UNCHANGED_ERROR_STOP,
    KEPT_CHATTING_STOP,
    NO_TOOL_CALLS_STOP,
)
from opentorus.agent.control.policies.budget import CANCELLED_MESSAGE, STEP_CAP_MESSAGE
from opentorus.agent.control.policies.completion import (
    CallableCompletion,
    NeverComplete,
)
from opentorus.tools.base import ToolResult

# --- helpers ---------------------------------------------------------------------------


def _ctx(**overrides) -> PolicyContext:
    base = dict(
        steps_run=1,
        tool_calls_this_run=0,
        elapsed_seconds=0.0,
        last_tool_ok=True,
        deliverable_satisfied=False,
        session_id="s",
    )
    base.update(overrides)
    return PolicyContext(**base)


def _result(ok: bool = True, content: str = "ok", **metadata) -> ToolResult:
    return ToolResult(tool_call_id="c", ok=ok, content=content, metadata=metadata)


# --- keys ---------------------------------------------------------------------------------


def test_stable_error_key_strips_volatile_tokens_only() -> None:
    raw = 'PROOF-0007 REJECTED. File "/tmp/opentorus-x/proof.v", line 9, characters 15-20: Error.'
    key = stable_error_key(raw)
    assert "PROOF-0007" not in key and "<id>" in key
    assert "/tmp/opentorus-x" not in key and "<tmp>" in key
    assert "line <n>, characters <n>" in key
    assert stable_error_key("Error: lemma1 not found") != stable_error_key(
        "Error: lemma2 not found"
    )


def test_tool_sig_is_order_independent() -> None:
    assert tool_sig("read_file", {"a": 1, "b": 2}) == tool_sig("read_file", {"b": 2, "a": 1})
    assert tool_sig("read_file", {}) == "read_file:{}"


# --- identical failures ---------------------------------------------------------------


def test_identical_failure_guard_ladder() -> None:
    guard = IdenticalFailureGuard()
    sig = tool_sig("exp_run", {"exp_id": "EXP-9999"})
    decisions = []
    for _ in range(_MAX_IDENTICAL_FAILURES):
        content, decision = guard.note_failure("exp_run", sig, "Tool exp_run failed: missing")
        decisions.append(decision)
    assert decisions[0] is None and decisions[1] is None
    assert decisions[2] is not None and decisions[2].action is PolicyAction.WARN
    assert decisions[2].reason_code is ReasonCode.REPEATED_IDENTICAL_FAILURE
    assert decisions[2].message.endswith("The run stops after 3 more identical failure(s).")
    assert decisions[-1] is not None and decisions[-1].action is PolicyAction.STOP
    assert decisions[-1].message == (
        "Stopped: exp_run failed 6 times with identical arguments and an identical error "
        "— no progress is possible without changing the call. The failing call and its "
        "error are preserved in the session log; the dossier holds the current state."
    )
    assert "[loop guard] This exact exp_run call has now failed 6 times" in content
    assert "The run stops after" not in content
    assert guard.stop_decision() is not None
    guard.note_success(sig)
    assert guard.streak == 0 and guard.stop_decision() is None
    # The run memory survives the streak reset (and reset_run).
    guard.reset_run()
    assert guard.failure_counts


def test_identical_failure_guard_revisit_note_and_streak_reset_on_change() -> None:
    guard = IdenticalFailureGuard()
    a, _ = guard.note_failure("read_file", "read_file:a", "Not a file: a")
    guard.note_failure("read_file", "read_file:b", "Not a file: b")
    again, decision = guard.note_failure("read_file", "read_file:a", "Not a file: a")
    assert "already tried this" not in a
    assert "already tried this exact call earlier in this run (2 times now)" in again
    assert decision is None and guard.streak == 1


def test_identical_failure_guard_success_of_other_tool_keeps_streak() -> None:
    guard = IdenticalFailureGuard()
    for _ in range(3):
        guard.note_failure("exp_run", "exp_run:x", "boom")
    guard.note_success("status:{}")
    assert guard.streak == 3


# --- unchanged error output -------------------------------------------------------------


def test_unchanged_error_guard_warns_then_stops() -> None:
    guard = UnchangedErrorGuard()
    error = "Blocked: run_shell is not available during prove."
    notes = [
        guard.note("run_shell", f"run_shell:{i}", error) for i in range(_MAX_UNCHANGED_ERROR_STOP)
    ]
    for note in notes[: _MAX_UNCHANGED_ERROR_ATTEMPTS - 1]:
        assert note == error
    assert notes[_MAX_UNCHANGED_ERROR_ATTEMPTS - 1] == (
        f"{error}\n\nYou have now called run_shell 4 times with different arguments and "
        "gotten this identical error every time. The arguments are not the problem — the "
        "error is telling you something you have not addressed yet. Read it literally and "
        "fix what it names, or record the obstruction with memory_add(kind=decisions) and "
        "take another route."
    )
    assert guard.last_decision is not None
    assert guard.last_decision.reason_code is ReasonCode.UNCHANGED_ERROR_OUTPUT
    assert guard.stop is not None and guard.stop.action is PolicyAction.STOP
    assert guard.stop.message.startswith(
        "Stopped: run_shell failed 8 times with different arguments"
    )


def test_unchanged_error_guard_ignores_distinct_errors_and_same_args() -> None:
    guard = UnchangedErrorGuard()
    for i in range(12):
        assert guard.note("proof_write", f"proof_write:{i}", f"error {i}") == f"error {i}"
    for _ in range(12):
        assert guard.note("proof_write", "proof_write:same", "same error") == "same error"
    assert guard.stop is None


# --- the tracker facade ------------------------------------------------------------------


def test_tracker_marks_last_tool_ok_and_leaves_exempt_tools_alone() -> None:
    tracker = ToolFailureTracker()
    assert tracker.last_tool_ok is True
    for _ in range(10):
        assert tracker.note_failure("lit_search", "lit_search:q", "no hits") == "no hits"
    assert tracker.last_tool_ok is False
    assert tracker.stop_decision() is None
    tracker.reset_run()
    assert tracker.last_tool_ok is True


def test_tracker_stop_prefers_the_unchanged_error_ceiling() -> None:
    tracker = ToolFailureTracker()
    for i in range(_MAX_UNCHANGED_ERROR_STOP):
        tracker.note_failure("run_shell", f"run_shell:{i}", "same block")
    stop = tracker.stop_decision()
    assert stop is not None and stop.reason_code is ReasonCode.UNCHANGED_ERROR_OUTPUT
    assert tracker.stop_message() == stop.message


# --- repeat calls ------------------------------------------------------------------------


def test_repeat_call_guard_reserves_then_blocks_reads() -> None:
    guard = RepeatCallGuard()
    args = {"path": "notes.md"}
    sig = tool_sig("read_file", args)
    assert guard.check("read_file", args, sig, "write_file").allowed
    guard.note_result("read_file", args, sig, True, "SENTINEL")
    kinds = []
    for _ in range(_MAX_CACHED_RESERVES + 1):
        verdict = guard.check("read_file", args, sig, lambda: "write_file (e.g. analysis.md)")
        kinds.append(verdict.kind)
        assert verdict.decision is not None
        assert verdict.decision.reason_code is ReasonCode.CACHED_SOURCE_REREAD
    assert kinds == ["reserve"] * _MAX_CACHED_RESERVES + ["block"]
    served = guard.check("read_file", args, sig, "write_file")  # still blocked
    assert served.kind == "block"
    assert served.message.startswith(
        "read_file with these arguments has already been re-served from cache several times"
    )


def test_repeat_call_guard_blocks_non_cached_repeats_and_missing_files() -> None:
    guard = RepeatCallGuard()
    args = {"pattern": "**/*.py"}
    sig = tool_sig("glob_files", args)
    guard.note_result("glob_files", args, sig, True, "a.py")
    verdict = guard.check("glob_files", args, sig, "write_file (e.g. analysis.md)")
    assert verdict.kind == "block"
    assert verdict.message == (
        "Blocked repeat glob_files with the same arguments. Produce the deliverable now "
        "(write_file (e.g. analysis.md))."
    )
    missing = {"path": "src/algorithms.py"}
    msig = tool_sig("read_file", missing)
    guard.note_result("read_file", missing, msig, False, "Not a file: src/algorithms.py")
    verdict = guard.check("read_file", missing, msig, "write_file")
    assert verdict.kind == "block"
    assert verdict.message == (
        "Blocked repeat read_file on missing file src/algorithms.py. "
        "Use write_file with artifact IDs from status."
    )


def test_repeat_call_guard_never_blocks_exempt_tools() -> None:
    guard = RepeatCallGuard()
    for name in ("status", "lit_search", "paper_fetch", "paper_list"):
        sig = tool_sig(name, {})
        guard.note_result(name, {}, sig, True, "x")
        assert guard.check(name, {}, sig, "write_file").allowed


# --- acquisition -----------------------------------------------------------------------------


def test_acquisition_guard_streak_and_ratio_reason_codes() -> None:
    guard = AcquisitionGuard()
    for _ in range(3):
        guard.note_tool("lit_search")
        assert guard.nudge("lit_search") is None
    guard.note_tool("lit_search")
    decision = guard.nudge_decision("lit_search")
    assert decision is not None and decision.reason_code is ReasonCode.SEARCH_STREAK_LIMIT
    assert decision.message.startswith("\n\n[loop guard] This is consecutive search #4")
    guard.reset_run()
    for _ in range(15):
        guard.note_tool("paper_fetch")
    ratio = guard.nudge_decision("paper_fetch")
    assert ratio is not None and ratio.reason_code is ReasonCode.LOW_ACQUISITION_RATIO
    assert "15 searches/fetches so far against 0 calls" in ratio.message
    assert guard.nudge("paper_read") is None  # only rides on acquisition calls
    guard.note_tool("status")  # neutral
    assert (guard.acquisition_calls, guard.processing_calls) == (15, 0)


# --- chat-only stall -------------------------------------------------------------------------


def test_chat_only_stall_guard_variants() -> None:
    guard = ChatOnlyStallGuard()
    for i in range(_MAX_CHAT_ONLY_STALL - 1):
        assert guard.note_message(f"r{i}", in_gap_fill=False, tool_calls_this_run=0) is None
    stop = guard.note_message("last", in_gap_fill=False, tool_calls_this_run=0)
    assert stop is not None and stop.reason_code is ReasonCode.NO_ARTIFACT_PROGRESS
    assert stop.message == NO_TOOL_CALLS_STOP
    guard.reset()
    assert guard.note_message("same", in_gap_fill=True, tool_calls_this_run=2) is None
    repeated = guard.note_message("same", in_gap_fill=True, tool_calls_this_run=2)
    assert repeated is not None and repeated.message == KEPT_CHATTING_STOP
    guard.reset()
    guard.note_message("same", in_gap_fill=False, tool_calls_this_run=2)
    assert guard.note_message("same", in_gap_fill=False, tool_calls_this_run=2) is None


# --- budgets ------------------------------------------------------------------------------


def test_step_cap_policy() -> None:
    finite = StepCapPolicy(3)
    assert list(finite.steps()) == [0, 1, 2]
    assert finite.check(2) is None
    stop = finite.check(3)
    assert stop is not None and stop.reason_code is ReasonCode.STEP_CAP_REACHED
    assert stop.message == STEP_CAP_MESSAGE
    unbounded = StepCapPolicy(float("inf"))
    assert unbounded.unbounded and unbounded.check(10**9) is None


@pytest.mark.parametrize("limit", [None, 0, -5.0])
def test_wall_clock_policy_off(limit) -> None:
    assert WallClockPolicy(limit).check(10_000.0, 3) is None


def test_wall_clock_policy_boundaries() -> None:
    policy = WallClockPolicy(90.0)
    assert policy.check(89.999, 3) is None
    stop = policy.check(90.0, 3)
    assert stop is not None and stop.reason_code is ReasonCode.WALL_CLOCK_EXHAUSTED
    assert stop.message == (
        "Stopped: this run reached its wall-clock budget of 90s (elapsed 90s) after 3 model "
        "steps. Everything recorded so far is preserved; re-run to continue from the "
        "artifacts, or raise agent.max_wall_seconds."
    )


def test_cancellation_policy() -> None:
    assert CancellationPolicy(None).check() is None
    assert CancellationPolicy(lambda: False).check() is None
    stop = CancellationPolicy(lambda: True).check()
    assert stop is not None and stop.reason_code is ReasonCode.CANCELLED
    assert stop.action is PolicyAction.STOP and stop.message == CANCELLED_MESSAGE
    assert stop.message == "[stopped] cancelled by caller"


# --- no-progress window ----------------------------------------------------------------------


def test_no_progress_window_anchor_reset_stop() -> None:
    measure = {"n": 0}
    window = NoProgressWindow(3, lambda: measure["n"], lambda stalled: f"stalled {stalled}")
    assert not window.armed
    assert window.check(5) is None  # anchors at step 5
    assert window.armed and window.anchor_step == 5
    assert window.check(6) is None and window.check(7) is None
    stop = window.check(8)
    assert stop is not None and stop.message == "stalled 3"
    assert stop.reason_code is ReasonCode.NO_ARTIFACT_PROGRESS
    measure["n"] = 1
    assert window.check(9) is None  # progress re-anchors
    assert window.anchor_step == 9 and window.check(11) is None
    assert window.check(12) is not None
    window.reset()
    assert not window.armed


def test_no_progress_window_disabled_when_infinite() -> None:
    calls = {"n": 0}

    def measure() -> int:
        calls["n"] += 1
        return 0

    window = NoProgressWindow(float("inf"), measure, lambda s: "x")
    for step in range(50):
        assert window.check(step) is None
    assert calls["n"] == 0  # never even measured


# --- completion ----------------------------------------------------------------------------


def test_completion_policies() -> None:
    assert NeverComplete().is_complete() is False
    flag = {"done": False}
    policy = CallableCompletion(lambda: flag["done"])
    assert policy.is_complete() is False
    flag["done"] = True
    assert policy.is_complete() is True


# --- deliverables ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("satisfied", "complete", "gate", "expected"),
    [
        (False, None, None, False),
        (False, None, False, False),
        (False, None, True, True),
        (True, None, None, True),
        (True, False, None, False),
        (True, True, None, True),
        (True, False, True, False),  # a satisfied-but-incomplete deliverable wins over the gate
        (False, False, True, True),
    ],
)
def test_deliverable_session_ready_matrix(satisfied, complete, gate, expected) -> None:
    policy = DeliverablePolicy(
        session_gate=None if gate is None else (lambda: gate),
        deliverable_complete=None if complete is None else (lambda: complete),
    )
    policy.satisfied = satisfied
    assert policy.session_ready() is expected


def test_deliverable_needs_and_gap_fill_and_bootstrap() -> None:
    policy = DeliverablePolicy(
        bootstrap=("proof_write", {"x": 1}), deliverable_complete=lambda: False
    )
    assert policy.required_tool == "proof_write"
    assert policy.needs_deliverable(None) is True
    assert DeliverablePolicy().needs_deliverable(None) is False
    assert DeliverablePolicy().needs_deliverable(object()) is True
    assert policy.in_gap_fill() is False
    assert policy.bootstrap_call(None, root=None, ot_dir=None) == ("proof_write", {"x": 1})  # type: ignore[arg-type]
    policy.mark_satisfied()
    assert policy.in_gap_fill() is True
    assert policy.bootstrap_call(None, root=None, ot_dir=None) is None  # type: ignore[arg-type]
    # Swapping the bootstrap later never changes which tool counts as the deliverable.
    policy.bootstrap = ("status", {})
    assert policy.required_tool == "proof_write"


def test_deliverable_recovery_hints() -> None:
    plain = DeliverablePolicy(bootstrap=("proof_write", {}))
    assert plain.recovery_hint(None, 1, 0) == PROVE_RECOVERY_HINT
    assert plain.recovery_hint(None, 1, 2) == PROVE_RECOVERY_HINT_AFTER_TOOLS
    gap = DeliverablePolicy(bootstrap=("proof_write", {}), deliverable_complete=lambda: False)
    gap.mark_satisfied()
    assert gap.recovery_hint(None, 1, 5) == PROVE_GAPS_RECOVERY_HINT
    assert gap.gap_fill_hint() == PROVE_GAPS_RECOVERY_HINT
    lit = DeliverablePolicy(session_gate=lambda: False)
    assert lit.recovery_hint(None, 1, 0) == LIT_RECOVERY_HINT
    assert lit.recovery_hint(None, 1, 1) == LIT_RECOVERY_HINT_AFTER_TOOLS
    custom = DeliverablePolicy(session_gate=lambda: False, session_recovery_hint=lambda: "custom")
    assert custom.recovery_hint(None, 1, 0) == "custom"


def test_deliverable_result_and_pre_gate() -> None:
    policy = DeliverablePolicy(
        bootstrap=("proof_write", {}),
        pre_deliverable_gate=lambda: False,
        pre_deliverable_gate_detail=lambda: " Need ≥1 [parsed] papers in paper_list (have 0). ",
    )
    assert policy.pre_gate_block("exp_run") is None
    assert policy.pre_gate_block("proof_write") == (
        "Blocked proof_write: literature requirements not met (Need ≥1 [parsed] papers in "
        "paper_list (have 0).). Complete lit_search, paper_fetch, and memory_add (one "
        "observation per parsed paper) before drafting a proof."
    )
    assert pre_deliverable_block_message("proof_write", "x").startswith(
        "Blocked proof_write: literature requirements not met (x)."
    )
    ungated = DeliverablePolicy(bootstrap=("proof_write", {}), pre_deliverable_gate=lambda: False)
    assert "Preconditions not met." in (ungated.pre_gate_block("proof_write") or "")
    assert policy.note_deliverable_result("proof_write", _result(scope="exploration")) is False
    assert policy.satisfied is False
    assert policy.note_deliverable_result("proof_write", _result()) is True
    assert policy.satisfied is True
    assert DeliverablePolicy().note_deliverable_result("proof_write", _result()) is False


# --- workflow policy sets ------------------------------------------------------------------


def test_legacy_callback_policy_set() -> None:
    legacy = LegacyCallbackPolicySet(
        tool_gate=lambda name, args: "nope" if name == "run_shell" else None,
        stall_check=lambda: "stalled",
        session_gate=lambda: False,
    )
    gate = legacy.before_tool("run_shell", {})
    assert gate.action is PolicyAction.BLOCK and gate.reason_code is ReasonCode.TOOL_GATE_BLOCKED
    assert gate.message == "nope"
    assert legacy.before_tool("status", {}).allows
    stall = legacy.before_turn(_ctx())
    assert stall.stops and stall.reason_code is ReasonCode.NO_ARTIFACT_PROGRESS
    assert stall.message == "stalled"
    assert legacy.evaluate_completion(_ctx()).reason_code is ReasonCode.DELIVERABLE_MISSING
    assert legacy.evaluate_completion(_ctx(deliverable_satisfied=True)).allows
    assert LegacyCallbackPolicySet().evaluate_completion(_ctx()).allows
    outcome = ToolOutcome(name="status", ok=True, content="x")
    assert legacy.after_tool(outcome).allows and legacy.evaluate_progress(_ctx()).allows


def test_composite_policy_set_first_non_allow_wins() -> None:
    calls: list[str] = []

    class _Recording(NullPolicySet):
        def __init__(self, tag: str, decision: PolicyDecision) -> None:
            self.tag = tag
            self.decision = decision

        def before_tool(self, name: str, args: dict) -> PolicyDecision:
            calls.append(self.tag)
            return self.decision

    block = PolicyDecision(action=PolicyAction.BLOCK, reason_code=ReasonCode.TOOL_GATE_BLOCKED)
    ok = PolicyDecision(action=PolicyAction.ALLOW, reason_code=ReasonCode.OK)
    composite = CompositePolicySet(
        [_Recording("a", ok), _Recording("b", block), _Recording("c", ok)]
    )
    assert composite.before_tool("x", {}).blocks
    assert calls == ["a", "b"]  # c is never consulted
    assert first_blocking([ok, ok]).allows
    assert first_blocking([ok, block, ok]) is block
    warn = PolicyDecision(action=PolicyAction.WARN, reason_code=ReasonCode.OK, message="hm")
    only_warn = first_blocking([ok, warn])
    assert only_warn.action is PolicyAction.WARN and only_warn.message == "hm"
    assert only_warn.metadata["warnings"] == ["hm"]


def test_composite_policy_set_warning_does_not_hide_a_later_block() -> None:
    """A WARN keeps the consultation going; its message travels with the final decision."""
    calls: list[str] = []

    class _Recording(NullPolicySet):
        def __init__(self, tag: str, decision: PolicyDecision) -> None:
            self.tag = tag
            self.decision = decision

        def before_tool(self, name: str, args: dict) -> PolicyDecision:
            calls.append(self.tag)
            return self.decision

    ok = PolicyDecision(action=PolicyAction.ALLOW, reason_code=ReasonCode.OK)
    warn_a = PolicyDecision(action=PolicyAction.WARN, reason_code=ReasonCode.OK, message="slow")
    warn_b = PolicyDecision(action=PolicyAction.WARN, reason_code=ReasonCode.OK, message="costly")
    block = PolicyDecision(
        action=PolicyAction.BLOCK, reason_code=ReasonCode.TOOL_GATE_BLOCKED, message="no"
    )
    composite = CompositePolicySet(
        [_Recording("a", warn_a), _Recording("b", ok), _Recording("c", block), _Recording("d", ok)]
    )
    decision = composite.before_tool("x", {})
    assert decision.blocks and decision.message == "no"
    assert decision.metadata["warnings"] == ["slow"]
    assert calls == ["a", "b", "c"]  # the warning did not stop at "a"; "d" is after the block

    # Warnings only: the first warning is returned with every warning attached.
    calls.clear()
    composite = CompositePolicySet([_Recording("a", warn_a), _Recording("b", warn_b)])
    decision = composite.before_tool("x", {})
    assert decision.action is PolicyAction.WARN and decision.message == "slow"
    assert decision.metadata["warnings"] == ["slow", "costly"]
    assert calls == ["a", "b"]
    # A stop behind a warning wins too, and the original decisions are not mutated.
    stop = PolicyDecision(action=PolicyAction.STOP, reason_code=ReasonCode.CANCELLED)
    folded = first_blocking([warn_a, stop])
    assert folded.stops and folded.metadata["warnings"] == ["slow"]
    assert stop.metadata == {} and warn_a.metadata == {}


# --- permission translation and the null sink --------------------------------------------------


def test_permission_decision_to_policy_translates_all_three_outcomes() -> None:
    from opentorus.agent.control.policies import permission_decision_to_policy
    from opentorus.permissions.policy import PermissionDecision

    denied = PermissionDecision(
        allowed=False,
        reason="Safe mode is read-only.",
        requires_confirmation=False,
        risk_level="high",
    )
    policy = permission_decision_to_policy(denied)
    assert policy.blocks and policy.reason_code is ReasonCode.PERMISSION_DENIED
    assert policy.message == "Blocked: Safe mode is read-only."
    assert policy.metadata == {"risk_level": "high", "reason": "Safe mode is read-only."}

    confirm = PermissionDecision(
        allowed=True, requires_confirmation=True, reason="destructive command", risk_level="high"
    )
    policy = permission_decision_to_policy(confirm)
    assert policy.action is PolicyAction.WARN and policy.allows and not policy.blocks
    assert policy.message == "Requires confirmation: destructive command"

    allowed = PermissionDecision(
        allowed=True, reason="ok", requires_confirmation=False, risk_level="low"
    )
    policy = permission_decision_to_policy(allowed)
    assert policy.action is PolicyAction.ALLOW and policy.reason_code is ReasonCode.OK
    assert policy.message == "" and policy.metadata == {}


def test_null_sink_discards_events() -> None:
    from opentorus.agent.control import NullSink, TurnStarted

    sink = NullSink()
    assert sink.emit(TurnStarted(step=1, session_id="s")) is None
    assert not hasattr(sink, "events")


# --- phase machine -----------------------------------------------------------------------------


class _Phase(Enum):
    A = "a"
    B = "b"
    C = "c"


def test_phase_machine_transitions() -> None:
    machine = PhaseMachine({_Phase.A: {_Phase.B}, _Phase.B: frozenset({_Phase.A, _Phase.C})})
    assert machine.can_transition(_Phase.A, _Phase.B)
    assert not machine.can_transition(_Phase.A, _Phase.C)
    assert machine.is_terminal(_Phase.C) and not machine.is_terminal(_Phase.A)
    assert machine.allowed(_Phase.B) == frozenset({_Phase.A, _Phase.C})
    machine.assert_transition(_Phase.B, _Phase.C)
    with pytest.raises(InvalidTransition) as info:
        machine.assert_transition(_Phase.C, _Phase.A)
    assert "Invalid transition c -> a" in str(info.value)
    assert info.value.source is _Phase.C and info.value.target is _Phase.A
    with pytest.raises(InvalidTransition):
        machine.assert_transition(_Phase.A, _Phase.C)


def test_policy_decision_helpers() -> None:
    stop = PolicyDecision(action=PolicyAction.STOP, reason_code=ReasonCode.CANCELLED)
    assert stop.stops and not stop.allows and not stop.blocks
    pause = PolicyDecision(action=PolicyAction.PAUSE, reason_code=ReasonCode.BUDGET_EXHAUSTED)
    assert pause.stops
    warn = PolicyDecision(action=PolicyAction.WARN, reason_code=ReasonCode.OK)
    assert warn.allows and not warn.stops
    assert ReasonCode.OK == "OK" and PolicyAction.ALLOW == "allow"
