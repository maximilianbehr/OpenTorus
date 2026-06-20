"""Persistent line-editing history for the interactive session.

Wires Python's built-in :mod:`readline` into the REPL so that:

* the up/down arrow keys walk previous inputs, and
* ``Ctrl+R`` performs an incremental reverse search through history.

History is stored at the user level (``~/.opentorus/repl_history``, like the
cross-workspace knowledge base) so it persists across sessions and projects,
mirroring an ordinary shell. Set ``$OPENTORUS_HISTORY_FILE`` to relocate it or
``$OPENTORUS_NO_HISTORY=1`` to disable persistence entirely.

The module degrades gracefully: if ``readline`` is unavailable (e.g. on a bare
Windows install) the REPL simply falls back to plain input with no history.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # readline is part of the stdlib on macOS/Linux but optional on Windows.
    import readline as _readline
except ImportError:  # pragma: no cover - platform dependent
    _readline = None  # type: ignore[assignment]

_MAX_HISTORY = 2000
_loaded_path: Path | None = None


def readline_available() -> bool:
    """Whether interactive line editing (arrows + search) is available."""
    return _readline is not None


def history_path() -> Path | None:
    """Resolve the history file, honoring the disable/relocate env vars."""
    if os.environ.get("OPENTORUS_NO_HISTORY"):
        return None
    env = os.environ.get("OPENTORUS_HISTORY_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".opentorus" / "repl_history"


def setup_history() -> Path | None:
    """Activate readline editing and load saved history. Idempotent.

    Returns the resolved history file path (or ``None`` when readline is
    unavailable or persistence is disabled).
    """
    global _loaded_path
    if _readline is None:
        return None

    _readline.set_history_length(_MAX_HISTORY)

    path = history_path()
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            _readline.read_history_file(str(path))
    except OSError:
        return None
    _loaded_path = path
    return path


def save_history() -> None:
    """Persist the current in-memory history to disk (best effort)."""
    if _readline is None or _loaded_path is None:
        return
    try:
        _loaded_path.parent.mkdir(parents=True, exist_ok=True)
        _readline.write_history_file(str(_loaded_path))
    except OSError:
        pass


def enable_completion(match_fn) -> bool:
    """Wire TAB completion to ``match_fn(line, text) -> list[str]``.

    ``line`` is the full input buffer and ``text`` the word being completed.
    Handles both GNU readline and the libedit backend bundled with macOS. Returns
    ``False`` when readline is unavailable.
    """
    if _readline is None:
        return False

    def _completer(text: str, state: int) -> str | None:
        buffer = _readline.get_line_buffer()
        matches = match_fn(buffer, text)
        return matches[state] if 0 <= state < len(matches) else None

    _readline.set_completer(_completer)
    _readline.set_completer_delims(" \t\n")
    if _readline.__doc__ and "libedit" in _readline.__doc__:
        _readline.parse_and_bind("bind ^I rl_complete")
    else:
        _readline.parse_and_bind("tab: complete")
    return True


def recent_history(limit: int = 20) -> list[str]:
    """Return up to ``limit`` most recent history entries (newest last)."""
    if _readline is None:
        return []
    length = _readline.get_current_history_length()
    start = max(1, length - limit + 1)
    items: list[str] = []
    for index in range(start, length + 1):
        item = _readline.get_history_item(index)
        if item:
            items.append(item)
    return items
