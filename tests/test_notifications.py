"""Tests for desktop notifications."""

from __future__ import annotations

import sys
from unittest.mock import patch

from opentorus.config import default_config
from opentorus.notifications import (
    notify_permission_required,
    notify_turn_complete,
    send_notification,
    should_notify,
    terminal_likely_background,
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
        native.assert_called_once_with("Title", "Body")


def test_notify_permission_required(monkeypatch) -> None:
    config = default_config()
    config.ui.notify_only_unfocused = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    with patch("opentorus.notifications.send_notification", return_value=True) as send:
        assert notify_permission_required(config.ui, description="run pytest") is True
        send.assert_called_once()
