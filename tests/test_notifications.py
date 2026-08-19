"""Tests for desktop notifications."""

from __future__ import annotations

import sys
from unittest.mock import patch

from opentorus.config import default_config
from opentorus.notifications import (
    _applescript_string,
    _notify_native,
    format_elapsed,
    notify_permission_required,
    notify_turn_complete,
    plain_snippet,
    send_notification,
    should_notify,
    terminal_likely_background,
    truncate_words,
)


def test_terminal_likely_background_respects_tty(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert terminal_likely_background() is False
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert terminal_likely_background() is True


def test_should_notify_respects_ui_config(monkeypatch) -> None:
    config = default_config()
    config.ui.notifications_enabled = False
    assert should_notify(config.ui) is False

    config.ui.notifications_enabled = True
    config.ui.notify_on_turn_complete = False
    assert should_notify(config.ui) is False

    config.ui.notify_on_turn_complete = True
    config.ui.notify_only_unfocused = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert should_notify(config.ui) is False

    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert should_notify(config.ui) is True


def test_permission_notify_ignores_turn_complete_flag() -> None:
    config = default_config()
    config.ui.notify_on_turn_complete = False
    config.ui.notify_on_permission = True
    assert should_notify(config.ui, permission=True) is True


def test_notify_turn_complete_honors_min_elapsed(monkeypatch) -> None:
    config = default_config()
    config.ui.notify_only_unfocused = False
    with patch("opentorus.notifications.send_notification", return_value=True) as send:
        assert notify_turn_complete(config.ui, summary="done", elapsed_seconds=1.0) is False
        send.assert_not_called()
        assert notify_turn_complete(config.ui, summary="done", elapsed_seconds=5.0) is True
        send.assert_called_once()


def test_send_notification_uses_native_backend(monkeypatch) -> None:
    with patch("opentorus.notifications._notify_native", return_value=True) as native:
        assert send_notification("Title", "Body") is True
        native.assert_called_once_with("Title", "Body", "normal")


def test_notify_permission_required(monkeypatch) -> None:
    config = default_config()
    config.ui.notify_only_unfocused = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    with patch("opentorus.notifications.send_notification", return_value=True) as send:
        assert notify_permission_required(config.ui, description="run pytest") is True
        send.assert_called_once()


def test_send_notification_survives_a_backend_timeout(monkeypatch) -> None:
    """A native backend that hits its subprocess timeout (a slow PowerShell on a Windows
    CI runner did) is a courtesy that failed, never an exception out of the agent turn:
    the bell fallback is tried and the call returns normally."""
    import subprocess

    def _slow(title: str, message: str, urgency: str) -> bool:
        raise subprocess.TimeoutExpired(cmd=["powershell"], timeout=5)

    with (
        patch("opentorus.notifications._notify_native", side_effect=_slow),
        patch("opentorus.notifications._notify_bell", return_value=False) as bell,
    ):
        assert send_notification("Title", "Body") is False
        bell.assert_called_once_with("Title", "Body", "normal")


# ----------------------------------------------------------------- formatting


def test_format_elapsed_reads_like_speech() -> None:
    assert format_elapsed(0.4) == "0s"
    assert format_elapsed(45) == "45s"
    assert format_elapsed(134) == "2m 14s"
    assert format_elapsed(3785) == "1h 03m"


def test_plain_snippet_flattens_markdown_to_the_first_prose_paragraph() -> None:
    md = (
        "## Summary\n\n"
        "- We **verified** the bound for `n ≤ 12` using [the script](scripts/run.py)\n"
        "- The conjecture *holds*; see PROOF-0003.\n\n"
        "```python\nprint('code')\n```\n"
    )
    assert plain_snippet(md) == (
        "We verified the bound for n ≤ 12 using the script · The conjecture holds; see PROOF-0003."
    )


def test_plain_snippet_keeps_math_and_falls_back_sensibly() -> None:
    # Single ``*``/``_`` are emphasis only between non-word characters: math survives.
    assert plain_snippet("a*b*c with x_1 and *emph*") == "a*b*c with x_1 and emph"
    # A lone heading is better than nothing; so is fenced code when that is all there is.
    assert plain_snippet("# Only a heading ##") == "Only a heading"
    assert plain_snippet("```\ncode only\n```") == "code only"
    assert plain_snippet("   \n\n") == ""


def test_truncate_words_cuts_at_a_word_boundary_with_an_ellipsis() -> None:
    text = "alpha beta gamma delta epsilon"
    assert truncate_words(text, 100) == text
    cut = truncate_words(text, 14)
    assert cut == "alpha beta…"
    assert len(cut) <= 14
    # No boundary near the cut: hard cut, still within the limit.
    assert truncate_words("a" * 50, 10) == "a" * 9 + "…"


def test_turn_complete_toast_has_elapsed_title_task_and_result(monkeypatch) -> None:
    config = default_config()
    config.ui.notify_only_unfocused = False
    summary = "## Result\n\nThe **bound** holds for every tested `n`.\n\nDetails follow."
    task = "Prove the *Crouzeix* conjecture for 3×3 matrices"
    with patch("opentorus.notifications.send_notification", return_value=True) as send:
        assert notify_turn_complete(config.ui, summary=summary, elapsed_seconds=134, task=task)
    send.assert_called_once_with(
        "OpenTorus finished in 2m 14s",
        "Task: Prove the Crouzeix conjecture for 3×3 matrices\nThe bound holds for every tested n.",
    )


def test_turn_complete_toast_without_task_or_summary(monkeypatch) -> None:
    config = default_config()
    config.ui.notify_only_unfocused = False
    with patch("opentorus.notifications.send_notification", return_value=True) as send:
        notify_turn_complete(config.ui, summary="   ", elapsed_seconds=10)
    send.assert_called_once_with("OpenTorus finished in 10s", "Finished without a final message.")


def test_permission_toast_names_action_reason_risk_and_is_critical(monkeypatch) -> None:
    config = default_config()
    with patch("opentorus.notifications.send_notification", return_value=True) as send:
        assert notify_permission_required(
            config.ui,
            description="ls **/*.py",
            reason="Command requires confirmation in ask mode.",
            risk_level="medium",
        )
    send.assert_called_once_with(
        "OpenTorus needs your approval",
        "Action: ls **/*.py\n"
        "Command requires confirmation in ask mode. (risk: medium)\n"
        "Approve in the terminal to continue.",
        urgency="critical",
    )


def test_linux_backend_escapes_markup_and_passes_urgency(monkeypatch) -> None:
    monkeypatch.setattr("opentorus.notifications.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "opentorus.notifications.shutil.which", lambda _name: "/usr/bin/notify-send"
    )
    with patch("opentorus.notifications.subprocess.run") as run:
        assert _notify_native("Title", "a < b & c", "critical") is True
    argv = run.call_args.args[0]
    assert argv[0] == "notify-send"
    assert argv[argv.index("--urgency") + 1] == "critical"
    assert argv[-2:] == ["Title", "a &lt; b &amp; c"]


def test_macos_backend_uses_applescript_string_literals(monkeypatch) -> None:
    # AppleScript has no single-quoted strings; the old helper produced a syntax error
    # that ``capture_output`` hid.
    assert _applescript_string('say "hi"\nnow') == '"say \\"hi\\"\\nnow"'
    monkeypatch.setattr("opentorus.notifications.platform.system", lambda: "Darwin")
    with patch("opentorus.notifications.subprocess.run") as run:
        assert _notify_native("T", "Body", "normal") is True
    script = run.call_args.args[0][-1]
    assert script == 'display notification "Body" with title "T"'
