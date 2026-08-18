"""OpenTorus CLI — ``campaign dashboard``: the optional, read-only terminal dashboard.

Registered on the ``campaign`` group defined in :mod:`opentorus.cli.campaign`. The
interactive view needs the ``dashboard`` extra (``pip install 'opentorus[dashboard]'``,
i.e. Textual); without it the command exits 1 with that instruction. The export
flags (``--plain`` / ``--json`` / ``--dot``) render the very same proof graph
``campaign tree`` shows through ``opentorus.campaign.proof_tree.render`` and never
import Textual, so they work on a base install.

Exit codes: 0 ok · 1 error (unknown campaign, unreadable workspace, missing extra).
"""

from __future__ import annotations

import typer
from rich.markup import escape

from opentorus.cli._base import _require_workspace_dir, console
from opentorus.cli.campaign import campaign_app
from opentorus.errors import OpenTorusError

# ``\[`` keeps Rich (Typer's help renderer) from reading ``[dashboard]`` as a style tag.
_DASHBOARD_HELP = (
    "Open a read-only terminal dashboard on a campaign's proof tree (optional dependency: "
    "pip install 'opentorus\\[dashboard]'). It shows the same graph as `campaign tree` — "
    "branches, obligations, claims, evidence, proof attempts, verifier runs — with the "
    "campaign's orchestration state on top and, separately labelled, the problem status "
    "derived from dossier artifacts. Keys: j/k move, enter expands/collapses, f/s cycle "
    "the kind/status filter, / searches, g jumps to the root, o to the next open "
    "obligation, r reloads, l toggles live refresh, q quits. Nothing is written: no event, "
    "no snapshot, no usage record. --plain/--json/--dot export the graph without the "
    "dashboard extra."
)


@campaign_app.command("dashboard", help=_DASHBOARD_HELP)
def campaign_dashboard(
    campaign_id: str = typer.Argument(..., help="Campaign id, e.g. CAMPAIGN-0001."),
    live: bool = typer.Option(
        False, "--live", help="Re-read the campaign files periodically (toggle with `l`)."
    ),
    refresh: float = typer.Option(
        2.0, "--refresh", min=0.2, help="Seconds between live re-reads (with --live or `l`)."
    ),
    plain: bool = typer.Option(
        False, "--plain", help="Print the indented text tree instead of opening the dashboard."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the graph as JSON (no dashboard)."),
    as_dot: bool = typer.Option(
        False, "--dot", help="Print the graph as a Graphviz digraph (no dashboard)."
    ),
) -> None:
    if sum(1 for flag in (plain, as_json, as_dot) if flag) > 1:
        console.print("[red]Choose one of --plain, --json, --dot.[/red]")
        raise typer.Exit(code=1)
    base = _require_workspace_dir()
    if plain or as_json or as_dot:
        # The export path is the ``campaign tree`` path: same builder, same renderers,
        # no Textual — so a base install can still get the graph out of this command.
        from opentorus.campaign.proof_tree.builder import build_proof_graph
        from opentorus.campaign.proof_tree.render import render_dot, render_json, render_plain
        from opentorus.campaign.store import open_campaign

        try:
            store = open_campaign(base, campaign_id)
            loaded = store.load()
        except OpenTorusError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(code=1) from exc
        graph = build_proof_graph(base, store.problem_id, loaded.snapshot)
        if as_json:
            text = render_json(graph)
        elif as_dot:
            text = render_dot(graph)
        else:
            text = render_plain(graph)
        typer.echo(text, nl=False)
        return
    from opentorus.dashboard import run_dashboard

    try:
        run_dashboard(base, campaign_id, live=live, refresh_seconds=refresh)
    except OpenTorusError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


__all__ = ["campaign_dashboard"]
