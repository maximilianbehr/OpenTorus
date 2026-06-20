"""Snapshot-testable panel renderers for the TUI.

Each function returns a Rich ``Panel`` built from existing data gatherers and the
``dispatch`` command core, so panels can be rendered headlessly (no TTY) and
asserted against in tests. ``build_dashboard`` composes them into a single
exported string for snapshot tests.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Group
from rich.panel import Panel

from opentorus.repl import (
    _format_actions,
    _format_patches,
    _format_tasks,
    _format_usage,
)
from opentorus.workspace import gather_status


def header_panel(start: Path | None = None) -> Panel:
    snap = gather_status(start)
    lines = [
        f"Workspace: {snap.workspace_root or 'none'}",
        f"Initialized: {'yes' if snap.initialized else 'no'}    Git: {snap.git_branch or 'n/a'}",
        f"Mode: {snap.project_mode or 'n/a'}    Style: {snap.operating_style or 'n/a'}",
        f"Claims: {snap.num_claims}  Experiments: {snap.num_experiments}  "
        f"Actions: {snap.num_actions}  Evidence: {snap.num_evidence}",
    ]
    return Panel("\n".join(lines), title="OpenTorus", border_style="blue")


def plan_panel(start: Path | None = None) -> Panel:
    return Panel(_format_tasks(start), title="Plan", border_style="cyan")


def actions_panel(start: Path | None = None) -> Panel:
    return Panel(_format_actions(start), title="Recent tool actions", border_style="green")


def patches_panel(start: Path | None = None) -> Panel:
    return Panel(_format_patches(start), title="Patches", border_style="magenta")


def usage_panel(start: Path | None = None) -> Panel:
    return Panel(_format_usage(start), title="Usage", border_style="yellow")


def _problems_text(start: Path | None) -> str:
    """Dossiers with the active one marked, plus a claims-by-status tally."""
    from opentorus.paths import find_workspace_root
    from opentorus.research.dossier import store
    from opentorus.workspace import workspace_dir

    root = find_workspace_root(start)
    if root is None:
        return "No workspace."
    ot = workspace_dir(root)
    dossiers = store.list_dossiers(ot)
    if not dossiers:
        return "No problems yet."
    active = store.get_active_problem(ot)
    lines: list[str] = []
    for d in dossiers:
        marker = "→ " if d.id == active else "  "
        by_status: dict[str, int] = {}
        for c in store.list_claims(ot, d.id):
            by_status[c.status] = by_status.get(c.status, 0) + 1
        tally = ", ".join(f"{n} {s}" for s, n in sorted(by_status.items())) or "no claims"
        lines.append(f"{marker}{d.id} [{d.status}] — {d.title}")
        lines.append(f"     {tally}")
    return "\n".join(lines)


def problems_panel(start: Path | None = None) -> Panel:
    return Panel(_problems_text(start), title="Problems", border_style="blue")


def dashboard_renderable(start: Path | None = None) -> Group:
    """Compose all panels into a single Rich renderable."""
    return Group(
        header_panel(start),
        problems_panel(start),
        plan_panel(start),
        actions_panel(start),
        patches_panel(start),
        usage_panel(start),
    )


def build_dashboard(start: Path | None = None, width: int = 100) -> str:
    """Render the dashboard to a plain string (for snapshot tests / headless use)."""
    from opentorus.ux import make_console

    console = make_console(width=width, record=True, file=None)
    with console.capture() as capture:
        console.print(dashboard_renderable(start))
    return capture.get()
