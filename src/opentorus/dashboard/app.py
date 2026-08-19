"""The Textual application: presentation only, over the pure adapters.

Layout (top to bottom): the overview header (campaign id / mode / phase / status and
the problem status line, labelled *derived from dossier artifacts*), a two-column
body — the proof-tree rows on the left, the selected node's detail on the right —,
a diagnostics panel that appears only when the graph carries validation issues, the
search input (shown while ``/`` is active) and the status bar with the current
filters and the key hints.

Every key press maps to one transition on :class:`~opentorus.dashboard.adapters.ViewState`
followed by a re-render; the app holds no state of its own besides the loaded
:class:`~opentorus.dashboard.adapters.DashboardData`, the visible rows and the live
timer. It never writes: the loader it is given re-reads the campaign files, and no
code path here touches the store, the dossier or the usage ledger (a test runs the
app headlessly with every writer monkeypatched to raise).
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.timer import Timer
from textual.widgets import Input, OptionList

from opentorus.campaign.proof_tree.models import ROOT_ID
from opentorus.dashboard.adapters import (
    DashboardData,
    DataLoader,
    TreeRowModel,
    ViewState,
    build_detail,
    detail_lines,
    issue_lines,
    next_open_obligation,
    overview_lines,
)
from opentorus.dashboard.widgets import (
    DetailPane,
    DiagnosticsPanel,
    OverviewHeader,
    StatusBar,
    TreePane,
)
from opentorus.errors import OpenTorusError


class CampaignDashboardApp(App[None]):
    """Read-only proof-tree dashboard for one campaign (see the module docstring)."""

    TITLE = "OpenTorus campaign dashboard (read-only)"
    CSS = """
    #body { height: 1fr; }
    #detail-scroll { width: 1fr; height: 1fr; }
    #search { height: 3; }
    """
    BINDINGS = [
        Binding("j", "cursor_down", "down", show=False),
        Binding("k", "cursor_up", "up", show=False),
        Binding("f", "cycle_kind", "kind filter", show=False),
        Binding("s", "cycle_status", "status filter", show=False),
        Binding("slash", "search", "search", show=False),
        Binding("escape", "clear_search", "clear search", show=False),
        Binding("g", "goto_root", "root", show=False),
        Binding("o", "next_obligation", "next open obligation", show=False),
        Binding("r", "reload", "reload", show=False),
        Binding("l", "toggle_live", "live refresh", show=False),
        Binding("q", "quit", "quit", show=False),
    ]

    def __init__(
        self,
        loader: DataLoader,
        *,
        initial: DashboardData | None = None,
        live: bool = False,
        refresh_seconds: float = 2.0,
    ) -> None:
        super().__init__()
        self._loader = loader
        self._data: DashboardData | None = initial
        self.state = ViewState(live=live)
        self.refresh_seconds = refresh_seconds
        self._timer: Timer | None = None
        self._rows: list[TreeRowModel] = []
        self._notice: str | None = None

    # -- composition -------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield OverviewHeader(id="overview")
        with Horizontal(id="body"):
            yield TreePane(id="tree")
            with VerticalScroll(id="detail-scroll"):
                yield DetailPane(id="detail")
        yield DiagnosticsPanel(id="diagnostics")
        yield Input(
            placeholder="search id / title / statement (enter applies, esc cancels)", id="search"
        )
        yield StatusBar(id="status")

    def on_mount(self) -> None:
        self.query_one("#search", Input).display = False
        if self._data is None:
            self._reload()
        else:
            self._render_all()
        if self.state.live:
            self._start_live()
        self.query_one(TreePane).focus()

    # -- data ---------------------------------------------------------------------------

    @property
    def data(self) -> DashboardData | None:
        return self._data

    @property
    def rows(self) -> list[TreeRowModel]:
        return list(self._rows)

    def _reload(self) -> None:
        """Re-run the loader; on failure keep the last good data and say so in the bar."""
        keep = self.state.current_id(self._rows)
        try:
            self._data = self._loader()
        except (OpenTorusError, OSError, ValueError) as exc:
            self._notice = f"reload failed: {exc}"
            self._render_status()
            return
        self._notice = "reloaded"
        self._render_all()
        if keep and self.state.select(keep, self._rows):
            self.query_one(TreePane).highlighted = self.state.cursor

    # -- rendering ------------------------------------------------------------------------

    def _render_all(self) -> None:
        data = self._data
        if data is None:
            self._render_status()
            return
        self.query_one(OverviewHeader).show(overview_lines(data.overview))
        self.query_one(DiagnosticsPanel).show(issue_lines(data.graph.issues))
        self._render_rows()

    def _render_rows(self) -> None:
        data = self._data
        if data is None:
            return
        self._rows = self.state.rows(data.graph)
        self.state.clamp(self._rows)
        self.query_one(TreePane).show(self._rows, self.state.cursor)
        self._render_detail()
        self._render_status()

    def _render_detail(self) -> None:
        data = self._data
        if data is None:
            return
        node_id = self.state.current_id(self._rows)
        pane = self.query_one(DetailPane)
        if node_id is None:
            pane.show([])
            return
        detail = build_detail(
            data.graph, node_id, data.snapshot, routing_records=data.routing_records
        )
        pane.show(detail_lines(detail))

    def _render_status(self) -> None:
        self.query_one(StatusBar).show(self.state.filter_text(), self._notice)

    # -- events from widgets ------------------------------------------------------------------

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_index is None:
            return
        self.state.cursor = event.option_index
        self.state.clamp(self._rows)
        self._render_detail()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter on a row: expand/collapse when it has children (a leaf stays as is)."""
        idx = event.option_index
        if idx is None or not (0 <= idx < len(self._rows)):
            return
        row = self._rows[idx]
        if row.repeated or not row.has_children:
            self._notice = f"{row.node_id} has no children to expand"
            self._render_status()
            return
        self.state.toggle(row.node_id)
        self.state.cursor = idx
        self._notice = None
        self._render_rows()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.state.set_search(event.value)
        self._hide_search()
        self._notice = None
        self.state.cursor = 0
        self._render_rows()

    # -- actions --------------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        self.query_one(TreePane).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(TreePane).action_cursor_up()

    def action_cycle_kind(self) -> None:
        if self._data is None:
            return
        self.state.cycle_kind(self._data.graph)
        self.state.cursor = 0
        self._notice = None
        self._render_rows()

    def action_cycle_status(self) -> None:
        if self._data is None:
            return
        self.state.cycle_status(self._data.graph)
        self.state.cursor = 0
        self._notice = None
        self._render_rows()

    def action_search(self) -> None:
        box = self.query_one("#search", Input)
        box.value = self.state.search or ""
        box.display = True
        box.focus()

    def action_clear_search(self) -> None:
        box = self.query_one("#search", Input)
        if box.display:
            self._hide_search()
            return
        if self.state.search:
            self.state.set_search(None)
            self._render_rows()

    def action_goto_root(self) -> None:
        if self.state.select(ROOT_ID, self._rows):
            self.query_one(TreePane).highlighted = self.state.cursor

    def action_next_obligation(self) -> None:
        target = next_open_obligation(self._rows, self.state.current_id(self._rows))
        if target is None:
            self._notice = "no open obligation in the current view"
            self._render_status()
            return
        if self.state.select(target, self._rows):
            self._notice = None
            self.query_one(TreePane).highlighted = self.state.cursor

    def action_reload(self) -> None:
        self._reload()

    def action_toggle_live(self) -> None:
        self.state.live = not self.state.live
        if self.state.live:
            self._start_live()
        else:
            self._stop_live()
        self._render_status()

    async def action_quit(self) -> None:
        self._stop_live()
        self.exit()

    # -- helpers ----------------------------------------------------------------------------

    def _hide_search(self) -> None:
        box = self.query_one("#search", Input)
        box.display = False
        self.query_one(TreePane).focus()

    def _start_live(self) -> None:
        if self._timer is None:
            self._timer = self.set_interval(self.refresh_seconds, self._reload)

    def _stop_live(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None


__all__ = ["CampaignDashboardApp"]
