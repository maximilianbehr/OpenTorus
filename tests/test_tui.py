"""Headless tests for the panelled TUI (Milestone 33)."""

from __future__ import annotations

from pathlib import Path

from opentorus.research.tasks import create_task
from opentorus.tui.panels import (
    build_dashboard,
    header_panel,
    plan_panel,
)
from opentorus.workspace import init_workspace, workspace_dir


def test_dashboard_renders_all_sections(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    text = build_dashboard(tmp_path)
    for title in ("OpenTorus", "Plan", "Recent tool actions", "Patches", "Usage"):
        assert title in text


def test_dashboard_without_workspace_does_not_crash(tmp_path: Path) -> None:
    # An empty dir has no workspace; the dashboard should still render.
    text = build_dashboard(tmp_path)
    assert "OpenTorus" in text


def test_header_reflects_initialized_state(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    console_text = _panel_text(header_panel(tmp_path))
    assert "Initialized: yes" in console_text


def test_plan_panel_shows_tasks(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    create_task(ot, "code", "implement step one")
    text = _panel_text(plan_panel(tmp_path))
    assert "step one" in text


def _panel_text(panel) -> str:
    from rich.console import Console

    console = Console(width=100)
    with console.capture() as capture:
        console.print(panel)
    return capture.get()
