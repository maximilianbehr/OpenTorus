"""The dashboard's widgets: thin Textual wrappers around plain-text view-models.

Each widget renders lines the adapters computed; none of them reads a ledger, keeps
state of its own beyond what Textual needs, or interprets Rich markup (every string
is wrapped in a ``rich.text.Text`` so ``[equivalent]`` and friends print literally).
Every text widget keeps the last plain string it showed in ``.plain`` so tests (and
the app) can assert on content without depending on a Textual-version-specific
accessor. ``textual`` is imported here and in :mod:`opentorus.dashboard.app` only.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from opentorus.dashboard.adapters import TreeRowModel

KEY_HINTS = (
    "j/k or arrows: move  enter: expand/collapse  f: kind filter  s: status filter  "
    "/: search  esc: clear search  g: root  o: next open obligation  r: reload  "
    "l: live refresh  q: quit"
)


class PlainStatic(Static):
    """A ``Static`` that shows plain text (never markup) and remembers it in ``.plain``."""

    plain: str = ""

    def show_text(self, text: str) -> None:
        self.plain = text
        self.update(Text(text))


class OverviewHeader(PlainStatic):
    """The header block: campaign line(s) and the derived problem status line."""

    DEFAULT_CSS = """
    OverviewHeader {
        height: auto;
        padding: 0 1;
        border-bottom: solid $primary;
    }
    """

    def show(self, lines: list[str]) -> None:
        self.show_text("\n".join(lines))


class TreePane(OptionList):
    """The proof-tree rows; one option per visible row, highlighted = cursor."""

    DEFAULT_CSS = """
    TreePane {
        width: 1fr;
        height: 1fr;
        border-right: solid $primary;
    }
    """

    def show(self, rows: list[TreeRowModel], cursor: int) -> None:
        options = [Option(Text(row.text())) for row in rows]
        if not options:
            options = [Option(Text("(no nodes match the current filter/search)"), disabled=True)]
        self.set_options(options)
        if rows:
            self.highlighted = max(0, min(cursor, len(rows) - 1))
        else:
            self.highlighted = None


class DetailPane(PlainStatic):
    """The right pane: the selected node's detail lines."""

    DEFAULT_CSS = """
    DetailPane {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    """

    def show(self, lines: list[str]) -> None:
        self.show_text("\n".join(lines) if lines else "(select a node)")


class DiagnosticsPanel(PlainStatic):
    """Graph issues (missing refs, cycles, malformed records); hidden when there are none."""

    DEFAULT_CSS = """
    DiagnosticsPanel {
        height: auto;
        max-height: 8;
        padding: 0 1;
        border-top: solid $warning;
        color: $warning;
    }
    """

    def show(self, lines: list[str]) -> None:
        self.display = bool(lines)
        self.show_text("\n".join(["Graph issues:", *lines]) if lines else "")


class StatusBar(PlainStatic):
    """The bottom bar: current filters/search/live state, key hints, and load notices."""

    DEFAULT_CSS = """
    StatusBar {
        height: auto;
        padding: 0 1;
        border-top: solid $primary;
    }
    """

    def show(self, filters: str, notice: str | None = None) -> None:
        lines = [filters, KEY_HINTS]
        if notice:
            lines.append(notice)
        self.show_text("\n".join(lines))


__all__ = [
    "KEY_HINTS",
    "DetailPane",
    "DiagnosticsPanel",
    "OverviewHeader",
    "PlainStatic",
    "StatusBar",
    "TreePane",
]
