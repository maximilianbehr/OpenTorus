"""OpenTorus CLI — ``campaign tree``: the semantic proof tree of a campaign.

Registered on the ``campaign`` group defined in :mod:`opentorus.cli.campaign` (this
module only adds a command; the group, its help and its exit-code conventions live
there). Rendering is delegated to ``opentorus.campaign.proof_tree.render``; the tree
itself is built read-only by ``proof_tree.builder`` from the campaign snapshot merged
with the dossier and workspace ledgers.

Exit codes: 0 ok · 1 error (unknown campaign, unreadable workspace).
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markup import escape

from opentorus.cli._base import _require_workspace_dir, console
from opentorus.cli.campaign import campaign_app
from opentorus.errors import OpenTorusError

_TREE_HELP = (
    "Show the semantic proof tree of a campaign: the campaign's orchestration nodes "
    "(branches, obligations, failure signatures) merged with the dossier's artifacts "
    "(claims, evidence, proof attempts, experiments, reviews, theorem references) and the "
    "workspace verifier ledger. Every node shows its relation to the root and its own "
    "ledger status; a node status never upgrades the problem's derived status, which is "
    "printed once at the top (from `opentorus problem verdict`'s status gate). "
    "Default output is plain text; --json and --dot export the same graph."
)


@campaign_app.command("tree", help=_TREE_HELP)
def campaign_tree(
    campaign_id: str = typer.Argument(..., help="Campaign id, e.g. CAMPAIGN-0001."),
    plain: bool = typer.Option(False, "--plain", help="Indented text tree (default)."),
    as_json: bool = typer.Option(False, "--json", help="The graph as JSON (nodes, edges, issues)."),
    as_dot: bool = typer.Option(False, "--dot", help="The graph as a Graphviz digraph."),
    kinds: list[str] = typer.Option(
        [],
        "--kind",
        help="Only nodes of this kind (repeatable): root, branch, obligation, claim, lemma, "
        "counterexample, evidence, proof-attempt, verification, experiment, failed-attempt, "
        "review, theorem-reference. Ancestors are kept so the tree stays connected.",
    ),
    statuses: list[str] = typer.Option(
        [], "--status", help="Only nodes with this status (repeatable), e.g. open, closed."
    ),
    depth: int | None = typer.Option(
        None, "--depth", min=0, help="Maximum depth below the root in the plain view."
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Write the output to this file instead of stdout."
    ),
) -> None:
    from opentorus.campaign.proof_tree.builder import build_proof_graph
    from opentorus.campaign.proof_tree.render import (
        filter_graph,
        render_dot,
        render_json,
        render_plain,
    )
    from opentorus.campaign.store import open_campaign

    if sum(1 for flag in (plain, as_json, as_dot) if flag) > 1:
        console.print("[red]Choose one of --plain, --json, --dot.[/red]")
        raise typer.Exit(code=1)
    base = _require_workspace_dir()
    try:
        store = open_campaign(base, campaign_id)
        loaded = store.load()
    except OpenTorusError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    graph = build_proof_graph(base, store.problem_id, loaded.snapshot)
    kind_set = {k for k in kinds if k.strip()} or None
    status_set = {s for s in statuses if s.strip()} or None
    if as_json or as_dot:
        view = filter_graph(graph, kind_set, status_set) if (kind_set or status_set) else graph
        text = render_json(view) if as_json else render_dot(view)
    else:
        text = render_plain(graph, kinds=kind_set, statuses=status_set, max_depth=depth)
    if out is not None:
        from opentorus.atomicio import atomic_write_text

        try:
            atomic_write_text(out, text)
        except OSError as exc:
            console.print(f"[red]Could not write {escape(str(out))}: {escape(str(exc))}[/red]")
            raise typer.Exit(code=1) from exc
        console.print(
            f"Wrote {escape(str(out))} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)"
        )
        return
    # ``typer.echo`` rather than the Rich console: tree lines must not be soft-wrapped
    # or markup-interpreted, and the JSON must stay byte-exact for round trips.
    typer.echo(text, nl=False)


__all__ = ["campaign_tree"]
