"""Panelled terminal UI for OpenTorus.

The UI is built on Rich (already a dependency) so it needs no extra packages and
no live TTY for tests. All session logic still flows through the pure
``repl.dispatch`` command core, so the TUI is a thin presentation layer:
``panels`` builds snapshot-testable renderables, and ``app`` runs the
interactive loop.
"""

from opentorus.tui.app import run_tui
from opentorus.tui.panels import build_dashboard

__all__ = ["build_dashboard", "run_tui"]
