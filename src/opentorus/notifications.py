"""Best-effort desktop notifications for long agent runs.

Inspired by Crush: ping the user when a turn finishes or when permission is
required, especially for background / piped runs where the terminal is easy to
miss. Delivery is native OS notifications when available, with a terminal-bell
fallback.

A toast is a small box: the text it carries is reduced to plain prose first
(Markdown markers stripped, whitespace collapsed, cut at a word boundary), laid out
as a short labelled body, and escaped for the backend's markup so a ``<`` or ``&``
in a model answer can neither mangle the toast nor drop it.
"""

from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Literal
from xml.sax.saxutils import escape as _xml_escape

if TYPE_CHECKING:
    from opentorus.config import UIConfig

logger = logging.getLogger("opentorus")

_APP_NAME = "OpenTorus"

Urgency = Literal["low", "normal", "critical"]

# Characters kept for a toast line; roughly what a desktop notification shows.
_BODY_LIMIT = 160
_TASK_LIMIT = 80
_ACTION_LIMIT = 120


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


# --------------------------------------------------------------------------- text


def format_elapsed(seconds: float) -> str:
    """Render a duration the way a human would say it: ``45s``, ``2m 14s``, ``1h 03m``."""
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_RULE_RE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*(?:>\s?)*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)")
_QUOTE_RE = re.compile(r"^\s*(?:>\s?)+")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPHASIS_RE = re.compile(r"(\*\*|__|`)")
# ``*word*`` / ``_word_`` only when delimited by non-word characters, so the ``*`` in
# ``a*b*c`` and the ``_`` in ``x_1`` (math, not Markdown) survive.
_SINGLE_EMPHASIS_RE = re.compile(
    r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])"
)
_SENTENCE_END = (".", "!", "?", ":", ";")


def _strip_inline(line: str) -> str:
    line = _IMAGE_RE.sub(r"\1", line)
    line = _LINK_RE.sub(r"\1", line)
    line = _EMPHASIS_RE.sub("", line)
    line = _SINGLE_EMPHASIS_RE.sub(lambda m: m.group(1) or m.group(2), line)
    if line.lstrip().startswith("|"):
        # A table row: cells separated by a middle dot, no pipes.
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        line = " · ".join(c for c in cells if c)
    return " ".join(line.split())


def plain_snippet(text: str, *, limit: int = _BODY_LIMIT) -> str:
    """Reduce (possibly Markdown) text to one plain line that fits a toast.

    Takes the first paragraph of prose -- skipping fenced code, rules, table
    separators and headings, stripping list markers, emphasis and link targets,
    joining list items with a middle dot -- collapses whitespace, and cuts at a
    word boundary with an ellipsis. A document that is only a heading (or only
    code) falls back to that heading (or the flattened text).
    """
    pieces: list[str] = []
    heading = ""
    in_fence = False
    for raw in text.splitlines():
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence or _RULE_RE.match(raw) or _TABLE_SEP_RE.match(raw):
            continue
        if not raw.strip():
            if pieces:
                break
            continue
        if m := _HEADING_RE.match(raw):
            if pieces:
                break
            heading = heading or _strip_inline(m.group(1))
            continue
        is_item = bool(_BULLET_RE.match(raw))
        line = _strip_inline(_QUOTE_RE.sub("", _BULLET_RE.sub("", raw)))
        if not line:
            continue
        if pieces and is_item and not pieces[-1].endswith(_SENTENCE_END):
            pieces.append("·")
        pieces.append(line)
    snippet = " ".join(pieces) or heading
    if not snippet:
        # Nothing but code or decoration: fall back to the raw text, flattened.
        snippet = " ".join(_EMPHASIS_RE.sub("", text).split())
    return truncate_words(snippet, limit)


def truncate_words(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` characters at a word boundary, ending in ``…``."""
    if len(text) <= limit:
        return text
    head = text[: max(limit - 1, 1)]
    space = head.rfind(" ")
    if space >= limit // 2:
        head = head[:space]
    return head.rstrip(" ,;:-–—(") + "…"


# ------------------------------------------------------------------------ sending


def send_notification(title: str, message: str, *, urgency: Urgency = "normal") -> bool:
    """Send a desktop notification. Returns True when a backend accepted the send.

    ``message`` may span several lines; each backend receives it escaped for its
    own markup. ``urgency`` maps to the backend's hint where one exists
    (``critical`` keeps a toast on screen until dismissed on most Linux desktops).
    """
    title = " ".join(title.split()) or _APP_NAME
    message = "\n".join(line.rstrip() for line in message.strip().splitlines()).strip()
    if not message:
        message = title
    for attempt in (_notify_native, _notify_bell):
        try:
            if attempt(title, message, urgency):
                return True
        except (OSError, subprocess.SubprocessError) as exc:
            # A notification is a courtesy: a slow PowerShell/notify-send that hits its
            # 5-second timeout (seen on a Windows CI runner) must never surface as a
            # failed agent turn.
            logger.debug("Notification backend failed: %s", exc)
    return False


def notify_turn_complete(
    config: UIConfig,
    *,
    summary: str,
    elapsed_seconds: float,
    task: str | None = None,
) -> bool:
    """Toast for a finished agent turn: how long it took, which task, and its first line.

    ::

        OpenTorus finished in 2m 14s
        Task: Prove the Crouzeix conjecture for 3×3 matrices
        The conjecture holds for the tested family; see PROOF-0003.
    """
    if not should_notify(config):
        return False
    if elapsed_seconds < config.notify_min_elapsed_seconds:
        return False
    lines: list[str] = []
    task_line = plain_snippet(task or "", limit=_TASK_LIMIT)
    if task_line:
        lines.append(f"Task: {task_line}")
    lines.append(plain_snippet(summary, limit=_BODY_LIMIT) or "Finished without a final message.")
    title = f"{_APP_NAME} finished in {format_elapsed(elapsed_seconds)}"
    return send_notification(title, "\n".join(lines))


def notify_permission_required(
    config: UIConfig,
    *,
    description: str,
    reason: str | None = None,
    risk_level: str | None = None,
) -> bool:
    """Toast for a blocked turn: the action awaiting approval, why, and where to answer.

    ::

        OpenTorus needs your approval
        Action: pytest tests/ -q
        Command requires confirmation in ask mode. (risk: medium)
        Approve in the terminal to continue.
    """
    if not should_notify(config, permission=True):
        return False
    lines: list[str] = []
    # A command line or a path, verbatim: no Markdown stripping (``**`` is a glob there).
    action = truncate_words(" ".join(description.split()), _ACTION_LIMIT)
    if action:
        lines.append(f"Action: {action}")
    why = " ".join((reason or "").split())
    if why:
        if risk_level:
            why = f"{why} (risk: {risk_level})"
        lines.append(truncate_words(why, _BODY_LIMIT))
    lines.append("Approve in the terminal to continue.")
    return send_notification(
        f"{_APP_NAME} needs your approval", "\n".join(lines), urgency="critical"
    )


# ----------------------------------------------------------------------- backends


def _notify_native(title: str, message: str, urgency: Urgency = "normal") -> bool:
    system = platform.system()
    if system == "Linux":
        if shutil.which("notify-send") is None:
            return False
        icon = "dialog-question" if urgency == "critical" else "dialog-information"
        subprocess.run(
            [
                "notify-send",
                "--app-name",
                _APP_NAME,
                "--urgency",
                urgency,
                "--icon",
                icon,
                title,
                # The body is Pango-style markup on every major desktop; a literal
                # ``<`` or ``&`` from a model answer would otherwise be eaten.
                _xml_escape(message),
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    if system == "Darwin":
        script = (
            f"display notification {_applescript_string(message)}"
            f" with title {_applescript_string(title)}"
        )
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
            f"$t='{_escape_ps(_xml_escape(title))}'; $m='{_escape_ps(_xml_escape(message))}'; "
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


def _notify_bell(title: str, message: str, urgency: Urgency = "normal") -> bool:
    del title, message, urgency
    sys.stdout.write("\a")
    sys.stdout.flush()
    return True


def _applescript_string(text: str) -> str:
    """An AppleScript string literal: double-quoted, with backslash escapes.

    (AppleScript has no single-quoted strings; ``osascript -e`` receives the script
    verbatim, so no shell quoting is involved.)
    """
    escaped = (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _escape_ps(text: str) -> str:
    return text.replace("'", "''")
