"""Interactive launcher for the panelled TUI.

Thin presentation loop over the pure ``repl.dispatch`` core and the agent loop.
On each turn it redraws the dashboard, then either dispatches a slash command or
runs a natural-language task through the agent (with streamed output). All
safety and command logic lives in the shared core, not here.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from opentorus.tui.panels import dashboard_renderable
from opentorus.workspace import find_workspace_root, workspace_dir

PROMPT = "opentorus# "


def run_tui(console: Console | None = None, start: Path | None = None) -> None:
    from opentorus.approvals import make_console_confirm
    from opentorus.config import CONFIG_FILENAME, default_config, load_config
    from opentorus.repl import _run_agent, dispatch
    from opentorus.ux import StreamPrinter, make_console

    console = console or make_console()
    root = find_workspace_root(start)
    base = workspace_dir(root) if root is not None else None
    session_id = uuid.uuid4().hex

    config = default_config()
    if base is not None:
        config_path = base / CONFIG_FILENAME
        if config_path.is_file():
            config = load_config(config_path)

    _confirm = make_console_confirm(console, config=config)

    def _redraw() -> None:
        console.clear()
        console.print(dashboard_renderable(start))

    _redraw()
    while True:
        try:
            line = console.input(f"\n[bold cyan]{PROMPT}[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye.")
            return

        stripped = line.strip()
        if stripped and not stripped.startswith("/"):
            printer = StreamPrinter(console)
            answer = _run_agent(
                root, base, stripped, session_id=session_id, confirm=_confirm, on_text=printer
            )
            printer.finish(answer)
            _redraw()
            continue

        result = dispatch(line, start)
        if result.should_exit:
            return
        _redraw()
        if result.messages:
            console.print(Panel("\n".join(result.messages), title="Output", border_style="white"))
