"""``AgentLoop`` stays the facade its callers built against.

The control-plane extraction may add keyword-only parameters and delegate state to
policy objects, but every constructor parameter, private attribute, private method
and module-level constant that a caller or an older test reached for must still be
there and still write through to the live guard state.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from opentorus.agent import loop as loop_module
from opentorus.agent.control import legacy
from opentorus.agent.control.policies import anti_loop
from opentorus.agent.loop import AgentLoop
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir
from test_control_plane_characterization import M0_SIGNATURE

NEW_KEYWORD_ONLY = [
    "event_sink",
    "routing",
    "usage_tags",
    "policies",
    "should_stop",
    "isolate_history",
]

PRIVATE_ATTRIBUTES = [
    "_fail_streak",
    "_search_streak",
    "_acquisition_calls",
    "_processing_calls",
    "_deliverable_satisfied",
    "_deliverable_complete",
    "_task_id",
    "_pending_edits",
    "_last_tool_ok",
    "_fail_streak_key",
    "_fail_streak_tool",
    "_failure_counts",
    "_error_signatures",
    "_read_cache",
    "_reserve_counts",
    "_tool_sigs_ok",
    "_read_fail_paths",
    "_required_deliverable_tool",
    "_tool_gate",
    "_stall_check",
    "deliverable_bootstrap",
    "session_gate",
    "edited",
    "tool_calls_this_run",
    "tools_used_this_run",
]

PRIVATE_METHODS = [
    "_note_tool_failure",
    "_note_tool_success",
    "_note_unchanged_error",
    "_identical_failure_stop",
    "_wall_clock_stop",
    "_acquisition_nudge",
    "_budget_stop",
    "_screen_outbound",
    "_record_usage",
    "_run_tool",
    "_enforce",
    "_evaluate",
    "_session_ready",
    "_read_path",
]

CONSTANTS = [
    "_MAX_TOOL_PARSE_RETRIES",
    "_MAX_DELIVERABLE_RETRIES",
    "_MAX_CHAT_ONLY_STALL",
    "_IDENTICAL_FAILURE_WARN",
    "_MAX_IDENTICAL_FAILURES",
    "_MAX_UNCHANGED_ERROR_ATTEMPTS",
    "_MAX_UNCHANGED_ERROR_STOP",
    "_VOLATILE_IN_ERRORS",
    "_REPEAT_GUARD_EXEMPT",
    "_REPEAT_GUARD_TOOLS",
    "_MAX_CACHED_RESERVES",
    "_SEARCH_STREAK_TOOLS",
    "_SEARCH_STREAK_NEUTRAL",
    "_SEARCH_STREAK_WARN",
    "_ACQUISITION_TOOLS",
    "_ACQUISITION_MIN",
    "_ACQUISITION_RATIO",
]

HINTS = {
    "_PROVE_RECOVERY_HINT": legacy.PROVE_RECOVERY_HINT,
    "_PROVE_GAPS_RECOVERY_HINT": legacy.PROVE_GAPS_RECOVERY_HINT,
    "_PROVE_RECOVERY_HINT_AFTER_TOOLS": legacy.PROVE_RECOVERY_HINT_AFTER_TOOLS,
    "_LIT_RECOVERY_HINT": legacy.LIT_RECOVERY_HINT,
    "_LIT_RECOVERY_HINT_AFTER_TOOLS": legacy.LIT_RECOVERY_HINT_AFTER_TOOLS,
}


def _loop(tmp_path: Path) -> AgentLoop:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    return AgentLoop(tmp_path, ot, MockProvider(), registry, default_config())


def test_constructor_signature_is_the_m0_snapshot_plus_keyword_only() -> None:
    params = list(inspect.signature(AgentLoop.__init__).parameters.values())
    snapshot = [
        (p.name, "<empty>" if p.default is inspect.Parameter.empty else repr(p.default))
        for p in params
    ]
    assert snapshot[: len(M0_SIGNATURE)] == M0_SIGNATURE
    for p in params[: len(M0_SIGNATURE)]:
        assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, p.name
    appended = params[len(M0_SIGNATURE) :]
    assert [p.name for p in appended] == NEW_KEYWORD_ONLY
    for p in appended:
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, p.name
        assert p.default is None, p.name


def test_positional_construction_still_works(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    config = default_config()
    loop = AgentLoop(tmp_path, ot, MockProvider(), registry, config, 9, "sess-1", None)
    assert loop.max_steps == 9 and loop.session_id == "sess-1"


@pytest.mark.parametrize("name", PRIVATE_ATTRIBUTES)
def test_private_attributes_present(tmp_path: Path, name: str) -> None:
    loop = _loop(tmp_path)
    assert hasattr(loop, name)


@pytest.mark.parametrize("name", PRIVATE_METHODS)
def test_private_methods_present(tmp_path: Path, name: str) -> None:
    loop = _loop(tmp_path)
    assert callable(getattr(loop, name))


@pytest.mark.parametrize("name", CONSTANTS)
def test_constants_importable_from_loop_and_identical(name: str) -> None:
    assert getattr(loop_module, name) is getattr(anti_loop, name)


@pytest.mark.parametrize(("name", "text"), sorted(HINTS.items()))
def test_hint_constants_importable_from_loop(name: str, text: str) -> None:
    assert getattr(loop_module, name) == text


def test_helper_aliases_importable_from_loop() -> None:
    assert loop_module._stable_error_key is anti_loop.stable_error_key
    assert loop_module._tool_sig is anti_loop.tool_sig
    assert callable(loop_module._shell_command_likely_edits)
    assert loop_module._shell_command_likely_edits("python run.py") is True
    assert loop_module._shell_command_likely_edits("ls -la") is False
    assert loop_module.ConfirmCallback is not None


def test_private_setters_write_through_to_the_guards(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop._search_streak += 3
    loop._acquisition_calls = 15
    loop._processing_calls = 0
    assert loop._acquisition.search_streak == 3
    assert loop._acquisition.acquisition_calls == 15
    assert loop._acquisition_nudge("paper_fetch") is not None

    loop._fail_streak = 5
    loop._fail_streak_tool = "exp_run"
    assert loop._identical_failure_stop() is None
    loop._fail_streak = 6
    assert (
        loop._identical_failure_stop() is not None and "exp_run" in loop._identical_failure_stop()
    )

    loop._deliverable_satisfied = True
    loop._deliverable_complete = lambda: False
    assert loop._session_ready() is False
    assert loop._deliverable.in_gap_fill() is True

    loop.deliverable_bootstrap = ("status", {})
    assert loop._required_deliverable_tool is None  # fixed at construction, as before

    loop._pending_edits = [("a", "", "x")]
    assert loop._runner.pending_edits == [("a", "", "x")]
    loop._task_id = "TASK-0001"
    assert loop._task_id == "TASK-0001"
    loop._read_cache = {"read_file:{}": "x"}
    assert loop._repeat_guard.read_cache == {"read_file:{}": "x"}
    loop._last_tool_ok = False
    assert loop._runner.last_tool_ok is False


def test_edited_and_counters_survive_and_reset_as_before(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop.edited = True
    loop.tool_calls_this_run = 4
    loop.tools_used_this_run = ["status"]
    loop.run("hello")  # the mock answers in chat
    assert loop.edited is True  # never reset by run()
    assert loop.tool_calls_this_run == 0 and loop.tools_used_this_run == []
