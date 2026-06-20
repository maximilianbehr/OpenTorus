"""Best-effort desktop notifications for long agent runs.

Inspired by Crush: ping the user when a turn finishes or when permission is
required, especially for background / piped runs where the terminal is easy to
miss. Delivery is native OS notifications when available, with a terminal-bell
fallback.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentorus.config import UIConfig

logger = logging.getLogger("opentorus")

_APP_NAME = "OpenTorus"


def terminal_likely_background() -> bool:
    """Heuristic: stdout is not an interactive terminal (piped, CI, detached)."""
    return not sys.stdout.isatty()


def should_notify(config: UIConfig, *, permission: bool = False) -> bool:
    """Return whether a desktop notification should be attempted."""
    if not config.notifications_enabled:
        return False
    if permission:
        return config.notify_on_permission
    if not config.notify_on_turn_complete:
        return False
    if config.notify_only_unfocused and not terminal_likely_background():
        return False
    return True


def send_notification(title: str, message: str) -> bool:
    """Send a desktop notification. Returns True when a backend accepted the send."""
    title = title.strip() or _APP_NAME
    message = message.strip()
    if not message:
        message = title
    for attempt in (_notify_native, _notify_bell):
        try:
            if attempt(title, message):
                return True
        except OSError as exc:
            logger.debug("Notification backend failed: %s", exc)
    return False


def notify_turn_complete(config: UIConfig, *, summary: str, elapsed_seconds: float) -> bool:
    if not should_notify(config):
        return False
    if elapsed_seconds < config.notify_min_elapsed_seconds:
        return False
    snippet = " ".join(summary.split())
    if len(snippet) > 160:
        snippet = snippet[:157] + "…"
    body = snippet or "Agent turn finished."
    return send_notification(f"{_APP_NAME} finished", body)


def notify_permission_required(config: UIConfig, *, description: str) -> bool:
    if not should_notify(config, permission=True):
        return False
    body = description.strip() or "Permission required to continue."
    if len(body) > 160:
        body = body[:157] + "…"
    return send_notification(f"{_APP_NAME} is waiting…", body)


def _notify_native(title: str, message: str) -> bool:
    system = platform.system()
    if system == "Linux":
        if shutil.which("notify-send") is None:
            return False
        subprocess.run(
            ["notify-send", "--app-name", _APP_NAME, title, message],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    if system == "Darwin":
        script = f"display notification {_shell_quote(message)} with title {_shell_quote(title)}"
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    if system == "Windows":
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
            "ContentType = WindowsRuntime] | Out-Null; "
            f"$t='{_escape_ps(title)}'; $m='{_escape_ps(message)}'; "
            "$xml=New-Object Windows.Data.Xml.Dom.XmlDocument; "
            "$xml.LoadXml(\"<toast><visual><binding template='ToastText02'>"
            "<text id='1'>$t</text><text id='2'>$m</text>"
            '</binding></visual></toast>"); '
            "$toast=[Windows.UI.Notifications.ToastNotification]::new($xml); "
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('OpenTorus').Show($toast)"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    return False


def _notify_bell(title: str, message: str) -> bool:
    del title, message
    sys.stdout.write("\a")
    sys.stdout.flush()
    return True


def _shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _escape_ps(text: str) -> str:
    return text.replace("'", "''")
