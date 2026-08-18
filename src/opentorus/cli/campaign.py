"""OpenTorus CLI — the ``campaign`` group (start / resume / status / pause / stop /
list / verify).

Rendering only: every decision lives in ``opentorus.campaign``. Two statuses are
shown and labelled everywhere: the *campaign status* (orchestration — phase, budget,
branches, work items) and the *problem status*, which is derived from accepted
dossier artifacts (``opentorus problem verdict``). A completed campaign does not mean
the problem is solved.

Exit codes: 0 ok · 1 error · 2 refused configuration (unknown mode, too few branches,
negative or absent budgets, missing primary claim) or replay mismatch · 130 interrupted
(the campaign is paused with reason ``interrupted`` and can be resumed).
"""

from __future__ import annotations

import typer
from rich.markup import escape

from opentorus.cli._base import (
    SortedGroup,
    _emit_json,
    _load_workspace_config,
    _require_workspace_dir,
    _require_workspace_root,
    _resolve_problem_id,
    app,
    console,
)
from opentorus.errors import OpenTorusError

campaign_app = typer.Typer(
    cls=SortedGroup,
    help=(
        "Portfolio campaigns on one open problem: start/resume/pause/stop, status, verify. "
        "Campaign status describes orchestration (phase, budget, branches, work items). "
        "The mathematical status of the problem is derived from accepted dossier artifacts "
        "(`opentorus problem verdict`); a completed campaign does not mean the problem is "
        "solved."
    ),
)
app.add_typer(campaign_app, name="campaign")

_STATUS_NOTE = (
    "Campaign status != problem status: the campaign is orchestration state; the problem "
    "status is derived from dossier artifacts (`opentorus problem verdict`)."
)


def _fail(exc: Exception, *, code: int = 1) -> None:
    console.print(f"[red]{escape(str(exc))}[/red]")
    raise typer.Exit(code=code) from exc


def _engine():  # noqa: ANN202 - the engine type is imported lazily
    from opentorus.campaign.engine import CampaignEngine

    root = _require_workspace_root()
    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    return CampaignEngine(root, base, config, notice=lambda text: console.print(escape(text)))


@campaign_app.command("start")
def campaign_start(
    problem_id: str = typer.Argument(..., help="Dossier id, e.g. PROBLEM-0001."),
    mode: str | None = typer.Option(
        None,
        "--mode",
        help="prove-or-refute | exploration | survey (default: campaign.default_mode).",
    ),
    branches: int | None = typer.Option(
        None, "--branches", help="Branches to keep after de-duplication (>= 2 for prove-or-refute)."
    ),
    max_steps: int | None = typer.Option(
        None, "--max-steps", help="Model turns across all workers; 0 = unlimited on this axis."
    ),
    token_budget: int | None = typer.Option(None, "--token-budget", help="0 = unlimited."),
    max_wall_seconds: int | None = typer.Option(None, "--max-wall-seconds", help="0 = unlimited."),
    cost_budget: float | None = typer.Option(None, "--cost-budget", help="USD; 0 = unlimited."),
    no_primary_claim: bool = typer.Option(
        False,
        "--no-primary-claim",
        help=(
            "prove-or-refute only: refuse to create/designate the CONJECTURE primary claim "
            "from the statement (exit 2 with the manual remediation)."
        ),
    ),
    no_run: bool = typer.Option(
        False, "--no-run", help="Create and record the campaign but do not run its phases."
    ),
) -> None:
    """Start a campaign on a dossier and run it (prints the campaign id first).

    Campaign status = orchestration; problem status = `opentorus problem verdict`.
    A completed campaign does not mean the problem is solved.
    """
    from opentorus.campaign.engine import CampaignConfigError

    engine = _engine()
    base = engine.ot_dir
    try:
        pid = _resolve_problem_id(base, problem_id)
        record = engine.start(
            pid,
            mode=mode,
            branches=branches,
            max_steps=max_steps,
            token_budget=token_budget,
            max_wall_seconds=max_wall_seconds,
            cost_budget=cost_budget,
            create_primary_claim=not no_primary_claim,
            run=not no_run,
        )
    except CampaignConfigError as exc:
        _fail(exc, code=2)
        return
    except KeyboardInterrupt:
        console.print(
            "[yellow]Interrupted: the campaign is paused (reason 'interrupted'); "
            f"resume with `opentorus campaign resume {_newest_campaign(base, problem_id)}`."
            "[/yellow]"
        )
        raise typer.Exit(code=130) from None
    except OpenTorusError as exc:
        _fail(exc)
        return
    typer.echo(record.id)
    _print_summary(engine, record.id)


def _newest_campaign(base, problem_id: str) -> str:  # noqa: ANN001
    """The id to name in the interrupt note (the campaign just started, when found)."""
    from opentorus.campaign.paths import list_campaigns

    try:
        pid = _resolve_problem_id(base, problem_id)
        found = list_campaigns(base, problem_id=pid)
    except OpenTorusError:
        found = []
    return found[-1][1] if found else "<CAMPAIGN-ID>"


def _print_summary(engine, campaign_id: str) -> None:  # noqa: ANN001
    from opentorus.campaign.status import build_status_summary, render_status

    try:
        summary = build_status_summary(engine.ot_dir, campaign_id, clock=engine.clock)
    except OpenTorusError as exc:
        console.print(f"[yellow]{escape(str(exc))}[/yellow]")
        return
    console.print(escape(render_status(summary)))


@campaign_app.command("resume")
def campaign_resume(
    campaign_id: str = typer.Argument(..., help="Campaign id, e.g. CAMPAIGN-0001."),
) -> None:
    """Resume a paused campaign (idempotent: a completed/stopped one exits 0 with a note)."""
    engine = _engine()
    try:
        result = engine.resume(campaign_id)
    except KeyboardInterrupt:
        console.print(
            "[yellow]Interrupted: the campaign is paused (reason 'interrupted'); "
            "resume again to continue.[/yellow]"
        )
        raise typer.Exit(code=130) from None
    except OpenTorusError as exc:
        _fail(exc)
        return
    console.print(escape(result.message))
    if result.resumed:
        _print_summary(engine, result.record.id)


@campaign_app.command("status")
def campaign_status(
    campaign_id: str = typer.Argument(..., help="Campaign id, e.g. CAMPAIGN-0001."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show the campaign's orchestration state and, separately, the derived problem status."""
    from opentorus.campaign.status import build_status_summary, render_status

    base = _require_workspace_dir()
    try:
        summary = build_status_summary(base, campaign_id)
    except OpenTorusError as exc:
        _fail(exc)
        return
    if as_json:
        _emit_json(summary.model_dump(mode="json"))
        return
    console.print(escape(render_status(summary)))


@campaign_app.command("pause")
def campaign_pause(
    campaign_id: str = typer.Argument(..., help="Campaign id, e.g. CAMPAIGN-0001."),
    reason: str = typer.Option(..., "--reason", help="Why (recorded in the event log)."),
) -> None:
    """Pause a running campaign; it resumes at the phase it was in."""
    engine = _engine()
    try:
        snap = engine.pause(campaign_id, reason)
    except OpenTorusError as exc:
        _fail(exc)
        return
    resume_at = snap.resume_phase.value if snap.resume_phase else "?"
    console.print(
        f"{escape(snap.campaign_id)} paused (resume at {resume_at}): "
        f"{escape(snap.pause_reason or reason)}"
    )


@campaign_app.command("stop")
def campaign_stop(
    campaign_id: str = typer.Argument(..., help="Campaign id, e.g. CAMPAIGN-0001."),
    reason: str = typer.Option(..., "--reason", help="Why (required; recorded in the event log)."),
) -> None:
    """Stop a campaign for good (terminal; the log and artifacts stay)."""
    engine = _engine()
    try:
        snap = engine.stop(campaign_id, reason)
    except OpenTorusError as exc:
        _fail(exc)
        return
    console.print(f"{escape(snap.campaign_id)} stopped: {escape(snap.stop_reason or reason)}")
    console.print(escape(_STATUS_NOTE))


@campaign_app.command("list")
def campaign_list(
    problem: str | None = typer.Option(None, "--problem", help="Only this PROBLEM-XXXX."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """List campaigns (all problems, or one) with their campaign status and phase."""
    from opentorus.campaign.paths import list_campaigns
    from opentorus.campaign.store import CampaignStore

    base = _require_workspace_dir()
    pid: str | None = None
    try:
        if problem:
            pid = _resolve_problem_id(base, problem)
    except OpenTorusError as exc:
        _fail(exc)
        return
    rows: list[dict[str, object]] = []
    for problem_id, campaign_id in list_campaigns(base, problem_id=pid):
        row: dict[str, object] = {"campaign_id": campaign_id, "problem_id": problem_id}
        try:
            loaded = CampaignStore(base, problem_id, campaign_id).load()
            snap = loaded.snapshot
            row.update(
                {
                    "mode": snap.mode.value,
                    "status": snap.status.value,
                    "phase": snap.phase.value,
                    "branches": len(snap.branches),
                    "steps_used": snap.budget.steps_used,
                    "diagnostics": len(loaded.diagnostics) + len(snap.diagnostics),
                }
            )
        except OpenTorusError as exc:
            row["error"] = str(exc)
        rows.append(row)
    if as_json:
        _emit_json(rows)
        return
    if not rows:
        console.print("No campaigns yet. Start one with `opentorus campaign start PROBLEM-0001`.")
        return
    for row in rows:
        if "error" in row:
            console.print(
                f"{row['campaign_id']}  {row['problem_id']}  [red]{escape(str(row['error']))}[/red]"
            )
            continue
        console.print(
            f"{row['campaign_id']}  {row['problem_id']}  {row['mode']}  "
            f"status={row['status']}  phase={row['phase']}  branches={row['branches']}  "
            f"steps={row['steps_used']}"
            + (f"  diagnostics={row['diagnostics']}" if row["diagnostics"] else "")
        )
    console.print(escape(_STATUS_NOTE))


@campaign_app.command("verify")
def campaign_verify(
    campaign_id: str = typer.Argument(..., help="Campaign id, e.g. CAMPAIGN-0001."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Replay the event log and compare it with snapshot.json (exit 1 on mismatch)."""
    from opentorus.campaign.store import open_campaign

    base = _require_workspace_dir()
    try:
        report = open_campaign(base, campaign_id).verify_replay()
    except OpenTorusError as exc:
        _fail(exc)
        return
    if as_json:
        _emit_json(
            {
                "campaign_id": campaign_id.strip().upper(),
                "matches": report.matches,
                "diff": report.diff,
                "events_replayed": report.events_replayed,
                "snapshot_seq": report.snapshot_seq,
                "log_seq": report.log_seq,
                "diagnostics": [d.model_dump(mode="json") for d in report.diagnostics],
            }
        )
    else:
        verdict = (
            "[green]replay matches snapshot[/green]"
            if report.matches
            else "[red]replay MISMATCH[/red]"
        )
        console.print(
            f"{escape(campaign_id.strip().upper())}: {verdict} "
            f"({report.events_replayed} events replayed; snapshot seq {report.snapshot_seq}, "
            f"log seq {report.log_seq})"
        )
        for line in report.diff:
            console.print(f"  - {escape(line)}")
        for diag in report.diagnostics:
            console.print(f"  ! {diag.kind}: {escape(diag.message)}")
    if not report.matches:
        raise typer.Exit(code=1)
