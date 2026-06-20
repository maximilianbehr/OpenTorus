"""OpenTorus CLI — replay commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer

from opentorus.cli._base import (
    SortedGroup,
    _require_workspace_dir,
    app,
    console,
)

replay_app = typer.Typer(cls=SortedGroup, help="Review past sessions for auditability.")
app.add_typer(replay_app, name="replay")


@replay_app.command("last")
def replay_last() -> None:
    """Summarize the most recent session."""
    from opentorus.agent.replay import summarize_session

    ot_dir = _require_workspace_dir()
    console.print(summarize_session(ot_dir))


@replay_app.command("session")
def replay_session(
    session_id: str = typer.Argument(..., help="The session id to summarize."),
) -> None:
    """Summarize a specific session by id."""
    from opentorus.agent.replay import summarize_session

    ot_dir = _require_workspace_dir()
    console.print(summarize_session(ot_dir, session_id))
