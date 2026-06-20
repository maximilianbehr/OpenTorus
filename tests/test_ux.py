"""Tests for UX helpers: actionable error formatting (Milestone 15)."""

from __future__ import annotations

import logging

from rich.console import Console

from opentorus.ux import (
    ActivityIndicator,
    StreamPrinter,
    activity_label,
    format_command_error,
    format_trace_message,
    likely_cause,
    normalize_terminal_text,
    setup_logging,
)


def test_missing_binary_cause() -> None:
    cause, action = likely_cause(127, "", False)
    assert "PATH" in cause
    assert "install" in action.lower()


def test_timeout_cause() -> None:
    cause, action = likely_cause(124, "", True)
    assert "time" in cause.lower()
    assert "timeout" in action.lower()


def test_no_such_file_cause_from_stderr() -> None:
    cause, _ = likely_cause(1, "bash: no such file or directory", False)
    assert "does not exist" in cause


def test_permission_denied_cause() -> None:
    cause, _ = likely_cause(1, "Permission denied", False)
    assert "permission" in cause.lower()


def test_format_command_error_is_structured() -> None:
    message = format_command_error("pytest", 1, "E   assert False", timed_out=False)
    assert "Command failed: pytest" in message
    assert "Exit code: 1" in message
    assert "Likely cause:" in message
    assert "Next action:" in message


def test_format_command_error_empty_stderr() -> None:
    message = format_command_error("foo", 2, "", False)
    assert "(no stderr output)" in message


def test_activity_label_maps_phases_and_tools() -> None:
    assert activity_label("model") == "Thinking"
    assert activity_label("tool", "web_search") == "Searching the web"
    assert activity_label("tool", "run_shell") == "Running a command"
    # Unknown tools fall back to a generic "Running <name>" label.
    assert activity_label("tool", "frobnicate") == "Running frobnicate"


def test_activity_indicator_renderable_shows_label_and_timer() -> None:
    console = Console()
    indicator = ActivityIndicator(console, enabled=True)
    indicator.update("Searching the web")
    rendered = console.render_str("")  # warm up; no assertion needed
    assert rendered is not None
    text = indicator.__rich__().plain
    assert "Searching the web" in text
    assert "s" in text  # the elapsed-seconds suffix
    indicator.stop()


def test_activity_indicator_disabled_is_noop() -> None:
    console = Console()
    indicator = ActivityIndicator(console, enabled=False)
    indicator.update("Thinking")
    # Disabled: nothing is started, so there is no live status object.
    assert indicator._status is None


def test_stream_printer_pauses_indicator_on_first_chunk() -> None:
    class _FakeIndicator:
        def __init__(self) -> None:
            self.paused = 0

        def pause(self) -> None:
            self.paused += 1

    console = Console()
    fake = _FakeIndicator()
    printer = StreamPrinter(console, indicator=fake)
    printer("hello ")
    printer("world\n")
    assert fake.paused >= 1
    assert printer.streamed is True


def test_setup_logging_levels() -> None:
    logger = logging.getLogger("opentorus")
    setup_logging(verbose=False, debug=False)
    assert logger.level == logging.WARNING
    setup_logging(verbose=True, debug=False)
    assert logger.level == logging.INFO
    setup_logging(verbose=False, debug=True)
    assert logger.level == logging.DEBUG


def test_normalize_terminal_text_replaces_br_and_tables() -> None:
    table = normalize_terminal_text("| **Lemmas** | First item |")
    assert "**Lemmas**" in table
    assert "First item" in table
    assert "|" not in table
    br = normalize_terminal_text("Line one<br>Line two")
    assert "<br>" not in br
    assert "Line one" in br
    assert "Line two" in br


def test_format_trace_message_summarizes_proof_write_tool() -> None:
    content = (
        "created PROOF-0003 [sketch] at "
        ".opentorus/problems/PROBLEM-0001/proof_attempts/PROOF-0003.md\n"
        "Gaps recorded: 8\n\n"
        "## Theorem\n\nLong proof body…"
    )
    out = format_trace_message("tool", content, tool_name="proof_write")
    assert "PROOF-0003" in out
    assert "Gaps recorded: 8" in out
    assert "## Theorem" not in out
