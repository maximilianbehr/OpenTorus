"""Failed attempts must survive, and a run must be bounded in wall-clock time.

Three gaps, each observed in a real run rather than imagined:

* Compaction rewrites ``session.jsonl``, so the promise the loop prints — "the failing
  call and its error are preserved in the session log" — stopped being true as soon as
  a run was long enough to compact. A dead end survived as a tool name in a comma list.
* The identical-failure guard tracked a single key, so a model alternating between two
  failing calls reset the streak every time and circled indefinitely.
* Every guard assumes turns return. A single hung model call satisfies none of them.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.compaction import _failed_attempts, _summarize_turns
from opentorus.agent.session import SessionMessage
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


def _tool(name: str, content: str, ok: bool) -> SessionMessage:
    return SessionMessage(
        role="tool", content=content, metadata={"name": name, "ok": ok, "tool_call_id": "c"}
    )


# --- compaction keeps failures ------------------------------------------------


def test_failed_attempts_are_extracted_with_their_error() -> None:
    messages = [
        _tool("exp_run", "Tool exp_run failed: container image missing", ok=False),
        _tool("status", "observed output", ok=True),
    ]
    failures = _failed_attempts(messages)
    assert len(failures) == 1
    assert "exp_run" in failures[0] and "container image missing" in failures[0]


def test_identical_failures_collapse_to_one_dead_end() -> None:
    messages = [_tool("proof_write", "citation CLAIM-9 does not exist", ok=False) for _ in range(5)]
    assert len(_failed_attempts(messages)) == 1


def test_summary_carries_failures_and_warns_against_repeating() -> None:
    messages = [
        SessionMessage(role="user", content="prove the bound"),
        _tool("proof_submit", "REJECTED by coq: unsolved goals", ok=False),
        SessionMessage(role="assistant", content="I will try another route."),
    ]
    summary = _summarize_turns(messages)
    assert "proof_submit" in summary
    # The error text itself survives — a bare tool name teaches the model nothing.
    assert "unsolved goals" in summary
    assert "do NOT repeat" in summary


def test_successful_calls_are_not_listed_as_failures() -> None:
    messages = [_tool("status", "observed output", ok=True)]
    assert _failed_attempts(messages) == []
    assert "Failed attempts" not in _summarize_turns(messages)


def test_untagged_tool_messages_are_treated_as_successes() -> None:
    """Records written before the ok flag existed must not be read as failures."""
    legacy = SessionMessage(role="tool", content="observed output", metadata={"name": "status"})
    assert _failed_attempts([legacy]) == []


# --- non-consecutive dead ends ------------------------------------------------


def _loop(tmp_path: Path):
    from opentorus.agent.loop import AgentLoop

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    return AgentLoop(tmp_path, ot, MockProvider(), registry, default_config())


def test_alternating_failures_are_remembered(tmp_path: Path) -> None:
    """A fails, B fails, A fails again — the streak resets, the run memory does not."""
    loop = _loop(tmp_path)
    first = loop._note_tool_failure("read_file", "read_file:{'path':'a'}", "Not a file: a")
    assert "already tried this" not in first

    loop._note_tool_failure("read_file", "read_file:{'path':'b'}", "Not a file: b")
    repeat = loop._note_tool_failure("read_file", "read_file:{'path':'a'}", "Not a file: a")

    assert "already tried this" in repeat
    assert "2 times now" in repeat
    # The original error is still shown; the note is added, not substituted.
    assert "Not a file: a" in repeat


def test_consecutive_failures_are_left_to_the_streak_guard(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop._note_tool_failure("read_file", "read_file:{'path':'a'}", "Not a file: a")
    again = loop._note_tool_failure("read_file", "read_file:{'path':'a'}", "Not a file: a")
    # Consecutive repeats already have their own escalation; no double-warning.
    assert "already tried this" not in again


# --- wall-clock budget --------------------------------------------------------


def test_wall_clock_stop_is_off_by_default(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    assert loop.config.agent.max_wall_seconds is None
    assert loop._wall_clock_stop(run_started=0.0) is None


def test_wall_clock_stop_fires_and_explains_recovery(tmp_path: Path) -> None:
    import time

    loop = _loop(tmp_path)
    loop.config.agent.max_wall_seconds = 1.0
    # A run that started well in the past has spent its budget.
    stop = loop._wall_clock_stop(run_started=time.monotonic() - 30.0)
    assert stop is not None
    assert "wall-clock budget" in stop
    assert "preserved" in stop
    assert "max_wall_seconds" in stop


def test_wall_clock_stop_silent_within_budget(tmp_path: Path) -> None:
    import time

    loop = _loop(tmp_path)
    loop.config.agent.max_wall_seconds = 600.0
    assert loop._wall_clock_stop(run_started=time.monotonic() - 1.0) is None


# --- same error, different arguments ------------------------------------------


def test_changing_arguments_does_not_hide_an_unchanged_error(tmp_path: Path) -> None:
    """The blind spot both other guards share: they key on the whole triple.

    Found by the run digest on a recorded run: 36 proof_write failures across 26
    distinct argument sets, 11 of them returning one identical citation error. The
    model rewrote the proof body every time and never touched the citation.
    """
    loop = _loop(tmp_path)
    error = "Paper citation check failed: PAPER-0001 has no numbered result 2.2"

    notes = [
        loop._note_tool_failure("proof_write", f"proof_write:{{'body':'draft {i}'}}", error)
        for i in range(4)
    ]

    # Never the same call twice, so neither the streak nor the exact-repeat memory fires.
    assert loop._fail_streak == 1
    assert all("already tried this exact call" not in n for n in notes)

    assert "not the problem" not in notes[0], "must not fire on the first attempts"
    assert "arguments are not the problem" in notes[-1]
    assert "4 times with different arguments" in notes[-1]
    assert "record the obstruction" in notes[-1]


def test_different_errors_do_not_accumulate(tmp_path: Path) -> None:
    """A model making genuine progress hits a *new* wall each time; leave it alone."""
    loop = _loop(tmp_path)
    notes = [
        loop._note_tool_failure("proof_write", f"proof_write:{{'body':'{i}'}}", f"error {i}")
        for i in range(6)
    ]
    assert all("arguments are not the problem" not in n for n in notes)


def test_the_original_error_text_is_kept(tmp_path: Path) -> None:
    """The note is appended; the model still needs to read what actually went wrong."""
    loop = _loop(tmp_path)
    error = "Paper citation check failed: PAPER-0001 has no numbered result 2.2"
    for i in range(4):
        note = loop._note_tool_failure("proof_write", f"proof_write:{{'b':'{i}'}}", error)
    assert error in note
