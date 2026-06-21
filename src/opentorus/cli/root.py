"""OpenTorus CLI — root commands (split from the former monolithic cli.py)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from opentorus.actions import list_actions
from opentorus.cli._base import (
    BANNER,
    _cli_verbosity,
    _load_workspace_config,
    _require_workspace_dir,
    _require_workspace_root,
    _resolve_problem_id,
    app,
    console,
)
from opentorus.errors import OpenTorusError
from opentorus.workspace import gather_status, init_workspace


@app.command()
def chat() -> None:
    """Start the interactive OpenTorus session."""
    from opentorus.repl import run_repl

    run_repl(console=console)


@app.command()
def tui() -> None:
    """Start the panelled terminal UI (plan, actions, patches, usage)."""
    from opentorus.tui import run_tui

    run_tui(console=console)


@app.command(name="export")
def export_cmd(
    session_id: str = typer.Argument(..., help="The session id to export."),
    out: str = typer.Option(
        None, "--out", "-o", help="Output .zip path (default under .opentorus/bundles/)."
    ),
) -> None:
    """Export a session as a privacy-clean, shareable bundle."""
    from opentorus.bundle import export_session

    ot_dir = _require_workspace_dir()
    try:
        path = export_session(ot_dir, session_id, Path(out) if out else None)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Exported session {session_id}[/green] to {path}")


@app.command(name="import")
def import_cmd(
    bundle: str = typer.Argument(..., help="Path to a session bundle (.zip)."),
) -> None:
    """Import a session bundle read-only for review (never merges live data)."""
    from opentorus.bundle import import_bundle, read_bundle_manifest

    ot_dir = _require_workspace_dir()
    try:
        manifest = read_bundle_manifest(Path(bundle))
        dest = import_bundle(ot_dir, Path(bundle))
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Imported session {manifest.session_id}[/green] "
        f"({manifest.message_count} messages, {manifest.redacted_messages} redacted) "
        f"into {dest} [dim](read-only review copy)[/dim]"
    )


@app.command()
def run(
    ctx: typer.Context,
    task: str | None = typer.Argument(
        None, help="A natural-language task or goal (omit with --resume)."
    ),
    plan: bool = typer.Option(
        False, "--plan", help="Plan the goal into tasks and execute them one at a time."
    ),
    fresh: bool = typer.Option(
        False,
        "--fresh",
        help="With --plan: discard the existing task pool before planning (starts clean).",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Continue the last run (same session) or pending planned tasks.",
    ),
    no_retry_failed: bool = typer.Option(
        False,
        "--no-retry-failed",
        help="With --resume: do not reset failed tasks to proposed before running.",
    ),
    only_task: str | None = typer.Option(
        None,
        "--task",
        help="Run only this TASK-* id (e.g. TASK-0004), skipping other pending tasks.",
    ),
) -> None:
    """Run a task through the agent loop, or plan and execute a multi-step goal."""
    from opentorus.agent.loop import AgentLoop
    from opentorus.agent.run_state import RunState, load_run_state, save_run_state
    from opentorus.agent.run_summary import build_run_summary, format_run_summary
    from opentorus.agent.task_validation import snapshot_artifacts
    from opentorus.approvals import make_console_confirm
    from opentorus.errors import ProviderError
    from opentorus.providers.registry import get_provider
    from opentorus.tools.builtin import build_default_registry
    from opentorus.ux import ActivityIndicator, StreamPrinter, activity_label, make_llm_trace

    verbose, debug = _cli_verbosity(ctx)
    ot_dir = _require_workspace_dir()
    root = ot_dir.parent
    config = _load_workspace_config(ot_dir)

    session_id: str | None = None
    saved_state: RunState | None = None
    if resume:
        saved_state = load_run_state(ot_dir)
        if saved_state is None:
            console.print("[red]No saved run to resume.[/red] Run a task first.")
            raise typer.Exit(code=1)
        session_id = saved_state.session_id or None
        if task is None:
            task = saved_state.goal
        if saved_state.mode == "plan":
            plan = True
    elif task is None:
        console.print("[red]Missing task.[/red] Provide a goal or use --resume.")
        raise typer.Exit(code=1)

    _confirm = make_console_confirm(console, config=config)
    run_before = snapshot_artifacts(root, ot_dir)

    try:
        provider = get_provider(config)
        from opentorus.providers.tool_support import require_tool_calling_provider

        require_tool_calling_provider(
            provider, config, warn=lambda m: console.print(f"[yellow]{m}[/yellow]")
        )
        registry = build_default_registry(root, ot_dir, config)
        if plan:
            indicator = ActivityIndicator(console)
            transform = None
            if config.ui.render_math:
                from opentorus.mathtext import render_math_line

                transform = render_math_line
            printer = StreamPrinter(console, transform=transform, indicator=indicator)
            on_request, on_response, on_text, stream_llm, on_thinking, _trace = make_llm_trace(
                console,
                verbose=verbose,
                debug=debug,
                user_on_text=printer,
                indicator=indicator,
            )
            stream_llm = stream_llm and provider.supports_streaming

            def _progress(line: str) -> None:
                stripped = line.strip()
                if stripped.endswith("thinking…") or ": running " in stripped:
                    if ": running " in stripped:
                        tool = stripped.split(": running ", 1)[1].removesuffix("…")
                        indicator.update(activity_label("tool", tool))
                    else:
                        indicator.update("Thinking")
                    return
                indicator.pause()
                if line.startswith("  "):
                    console.print(f"[dim]  ↳ {stripped}[/dim]", new_line_start=True)
                else:
                    console.print(f"[bold]●[/bold] {line}", new_line_start=True)

            def _confirm_paused(decision, description, session_scope=None):
                indicator.pause()
                return _confirm(decision, description, session_scope)

            plan_goal: str | None = task
            if resume and saved_state is not None and not fresh:
                plan_goal = None

            try:
                from opentorus.agent.executor import execute_plan

                outcome = execute_plan(
                    root,
                    ot_dir,
                    provider,
                    registry,
                    config,
                    goal=plan_goal,
                    fresh=fresh and not resume,
                    confirm=_confirm_paused,
                    progress=_progress,
                    on_text=on_text,
                    on_llm_request=on_request,
                    on_llm_response=on_response,
                    stream_llm=stream_llm,
                    session_id=session_id,
                    retry_failed=resume and not no_retry_failed,
                    only_task_id=only_task,
                    on_thinking=on_thinking,
                )
            finally:
                indicator.stop()
                printer.finish("")
            if outcome.idle_reason:
                console.print(f"[yellow]{outcome.idle_reason}[/yellow]")
            for r in outcome.tasks:
                color = "green" if r.status == "done" else "red"
                console.print(f"[{color}]{r.task_id} → {r.status}[/{color}]: {r.answer}")
            if outcome.summary and outcome.tasks:
                console.print(f"\n[bold]Run summary:[/bold] {format_run_summary(outcome.summary)}")
            elif outcome.summary and outcome.idle_reason:
                console.print(f"[dim]Session totals: {format_run_summary(outcome.summary)}[/dim]")
            return

        transform = None
        if config.ui.render_math:
            from opentorus.mathtext import render_math_line

            transform = render_math_line
        run_indicator = ActivityIndicator(console) if verbose else None
        printer = StreamPrinter(console, transform=transform, indicator=run_indicator)
        on_request, on_response, on_text, stream_llm, on_thinking, _trace = make_llm_trace(
            console,
            verbose=verbose,
            debug=debug,
            user_on_text=printer,
            indicator=run_indicator,
        )
        stream_llm = stream_llm and provider.supports_streaming
        loop = AgentLoop(
            root,
            ot_dir,
            provider,
            registry,
            config,
            max_steps=config.agent.max_steps,
            session_id=session_id,
            confirm=_confirm,
            on_text=on_text,
            on_llm_request=on_request,
            on_llm_response=on_response,
            stream_llm=stream_llm,
            on_thinking=on_thinking,
        )
        prompt = task
        if resume and saved_state is not None:
            prompt = (
                f"Continue the previous work on: {task}. Pick up where you left off using tools."
            )
        answer = loop.run(prompt)
        from opentorus.agent.verify import verify_and_repair

        verification = verify_and_repair(loop, root, ot_dir, config)
        save_run_state(
            ot_dir,
            RunState(goal=task, session_id=loop.session_id, mode="run"),
        )
    except KeyboardInterrupt:
        from opentorus.ux import format_interrupt_message

        sid = getattr(locals().get("loop"), "session_id", None) or session_id
        if sid:
            save_run_state(ot_dir, RunState(goal=task, session_id=sid, mode="run"))
        console.print(
            "\n[yellow]"
            + format_interrupt_message(
                "agent run stopped", resume_cmd=f'opentorus run "{task}" --resume'
            )
            + "[/yellow]"
        )
        raise typer.Exit(code=130) from None
    except ProviderError as exc:
        from opentorus.ux import format_provider_error

        console.print(f"[red]{format_provider_error(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc

    printer.finish(answer)
    summary = build_run_summary(
        root,
        ot_dir,
        before=run_before,
        tool_calls=loop.tool_calls_this_run,
    )
    console.print(f"\n[bold]Run summary:[/bold] {format_run_summary(summary)}")
    if verification.status not in ("not_needed", "passed"):
        color = "green" if verification.status == "repaired" else "red"
        console.print(f"[{color}]Verification: {verification.detail}[/{color}]")
    if verification.status == "failed":
        raise typer.Exit(code=1)


@app.command()
def usage(
    session_id: str = typer.Option(
        None, "--session", "-s", help="Limit to one session id (default: all)."
    ),
) -> None:
    """Show the local usage and (estimated) cost ledger."""
    from opentorus.usage import summarize_usage

    ot_dir = _require_workspace_dir()
    summary = summarize_usage(ot_dir, session_id)
    if summary.turns == 0:
        console.print("No usage recorded yet.")
        return
    scope = f"session {session_id}" if session_id else "all sessions"
    console.print(f"Usage ({scope}):")
    console.print(f"  turns:             {summary.turns}")
    console.print(f"  prompt tokens:     {summary.prompt_tokens}")
    console.print(f"  completion tokens: {summary.completion_tokens}")
    console.print(f"  total tokens:      {summary.total_tokens}")
    console.print(f"  est. cost (USD):   ${summary.cost_usd:.4f} (estimated)")
    console.print(f"  avg latency (ms):  {summary.avg_latency_ms}")
    if summary.by_model:
        console.print("  by model:")
        for model, tokens in sorted(summary.by_model.items()):
            console.print(f"    {model}: {tokens} tokens")


@app.command()
def diff(
    path: str | None = typer.Argument(None, help="Limit the diff to a path."),
    full: bool = typer.Option(False, "--full", help="Show the full diff without summarizing."),
) -> None:
    """Show a readable git diff of the working tree."""
    from opentorus.tools.git import git_diff

    root = _require_workspace_root()
    result = git_diff(root, path)
    if not result.is_repo:
        console.print(f"[yellow]{result.output}[/yellow]")
        return

    lines = result.output.splitlines()
    threshold = 200
    if full or len(lines) <= threshold:
        console.print(result.output)
        return

    # Summarize large diffs: list changed files, then show a capped excerpt.
    changed = [line[6:] for line in lines if line.startswith("+++ b/")]
    console.print(f"[bold]Large diff[/bold] ({len(lines)} lines). Changed files:")
    for name in changed:
        console.print(f"  M {name}")
    console.print("\n[dim]First lines (run `opentorus diff --full` for everything):[/dim]")
    console.print("\n".join(lines[:threshold]))


@app.command()
def shell(
    command: str = typer.Argument(..., help="The shell command to run."),
    timeout: int = typer.Option(30, "--timeout", help="Timeout in seconds."),
) -> None:
    """Run a shell command under the permission policy."""
    from opentorus.permissions.policy import PermissionDecision
    from opentorus.tools.shell import execute_command

    ot_dir = _require_workspace_dir()
    config = _load_workspace_config(ot_dir)

    def _confirm(decision: PermissionDecision) -> bool:
        console.print(f"\n[bold]OpenTorus wants to run:[/bold]\n\n  {command}\n")
        console.print(f"Reason: {decision.reason}")
        answer = console.input("Allow? [y] yes  [n] no: ").strip().lower()
        return answer in {"y", "yes"}

    console.print("[bold]●[/bold] Running shell command")
    decision, result = execute_command(
        ot_dir,
        command,
        config.permissions.mode,
        style=config.agent.style,
        review=config.agent.mode == "review",
        confirm=_confirm,
        timeout=timeout,
    )

    if result is None:
        if decision.risk_level == "blocked":
            console.print(f"[red]Blocked command:[/red] {command}")
            console.print(f"Reason: {decision.reason}")
        else:
            console.print(f"[yellow]Not run:[/yellow] {decision.reason}")
        raise typer.Exit(code=1)

    status_label = "ok" if result.exit_code == 0 else f"exit {result.exit_code}"
    console.print(f"[dim]⎿ {command} → {status_label}[/dim]")
    if result.stdout.strip():
        console.print(result.stdout.rstrip())
    if result.exit_code != 0:
        from opentorus.ux import format_command_error

        message = format_command_error(command, result.exit_code, result.stderr, result.timed_out)
        console.print(f"[red]{message}[/red]")
        raise typer.Exit(code=result.exit_code)
    if result.stderr.strip():
        console.print(f"[yellow]{result.stderr.rstrip()}[/yellow]")


@app.command("research")
def research(
    question: str = typer.Argument(..., help="The research question to pursue."),
    iterations: int = typer.Option(3, "--iterations", "-n", help="Global iteration cap."),
    cost_budget: float | None = typer.Option(
        None, "--cost-budget", help="Stop when estimated USD cost reaches this."
    ),
    token_budget: int | None = typer.Option(
        None, "--token-budget", help="Stop when estimated total tokens reach this."
    ),
    problem: str | None = typer.Option(
        None,
        "--problem",
        help="Attribute findings to this dossier (PROBLEM-XXXX). Default: the active "
        "problem, or unattributed if none — never silently a mismatched one.",
    ),
) -> None:
    """Pursue a research question autonomously within budgets (start or resume)."""
    from opentorus.agent.research_loop import run_research
    from opentorus.providers.registry import get_provider
    from opentorus.research.dossier import store

    base = _require_workspace_dir()
    root = base.parent
    config = _load_workspace_config(base)
    provider = get_provider(config)
    from opentorus.providers.tool_support import require_tool_calling_provider

    require_tool_calling_provider(
        provider, config, warn=lambda m: console.print(f"[yellow]{m}[/yellow]")
    )
    # Explicit target wins; otherwise findings attach to the active problem (or stay
    # unattributed) — they are never silently filed under an arbitrary dossier.
    if problem is not None:
        store.set_active_problem(base, _resolve_problem_id(base, problem))
    active = store.get_active_problem(base)
    if active is None:
        console.print(
            "[dim]No target problem; findings will be unattributed. Pass --problem "
            "PROBLEM-XXXX to attribute them to a dossier.[/dim]"
        )
    outcome = run_research(
        root,
        base,
        provider,
        config,
        question,
        max_iterations=iterations,
        cost_budget_usd=cost_budget,
        token_budget=token_budget,
    )
    console.print(
        f"[green]{outcome.iterations_run} iteration(s) this run[/green]; "
        f"{outcome.total_iterations} total. Stopped: {outcome.stopped_reason}."
    )
    if outcome.progress_path:
        console.print(f"Progress note: [bold].opentorus/{outcome.progress_path}[/bold].")
    console.print(
        f"Usage: {outcome.total_tokens} tokens, ${outcome.cost_usd:.4f} (estimated). "
        "All results are evidence, not proof."
    )


@app.command("prove")
def prove(
    ctx: typer.Context,
    problem_id: str | None = typer.Argument(
        None, help="Dossier id (defaults to the active problem)."
    ),
    disprove: bool = typer.Option(
        False,
        "--disprove",
        help="Prioritize counterexample / refutation instead of a proof sketch.",
    ),
    literature: bool = typer.Option(
        True,
        "--literature/--no-literature",
        help="Require lit_search + paper_fetch before proof_write (default: on).",
    ),
    min_papers: int | None = typer.Option(
        None,
        "--min-papers",
        min=0,
        help=(
            "Minimum preprints to fetch in phase 1 (0 = optional; >0 requires that many "
            "[parsed] papers). Default: config agent.prove_min_papers (0)."
        ),
    ),
    strategy: str = typer.Option(
        "",
        "--strategy",
        help="Optional attack strategy to scaffold first (proof_sketch, literature_map, …).",
    ),
    note: str = typer.Option("", "--note", help="Extra instructions for the agent."),
) -> None:
    """Run a focused agent session to draft a natural-language proof in the dossier."""
    from opentorus.agent.prove_loop import run_prove
    from opentorus.approvals import make_console_confirm
    from opentorus.errors import OpenTorusError, ProviderError
    from opentorus.providers.registry import get_provider
    from opentorus.research.dossier import store
    from opentorus.research.dossier.models import ATTACK_STRATEGIES
    from opentorus.research.dossier.strategies import create_approach
    from opentorus.ux import (
        ActivityIndicator,
        StreamPrinter,
        activity_label,
        configure_llm_cli_hooks,
    )

    verbose, debug = _cli_verbosity(ctx)
    ot_dir = _require_workspace_dir()
    root = ot_dir.parent
    config = _load_workspace_config(ot_dir)
    pid = _resolve_problem_id(ot_dir, problem_id)
    effective_min_papers = min_papers if min_papers is not None else config.agent.prove_min_papers

    try:
        store.require_dossier(ot_dir, pid)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    # Make the proved problem active so the agent's claim/evidence/experiment tools
    # attribute the artifacts they create to this dossier (not a stale active one).
    store.set_active_problem(ot_dir, pid)

    if strategy:
        key = strategy.strip().lower()
        if key not in ATTACK_STRATEGIES:
            console.print(
                f"[red]Unknown strategy '{strategy}'.[/red] "
                f"Choose from: {', '.join(sorted(ATTACK_STRATEGIES))}"
            )
            raise typer.Exit(code=1)
        approach = create_approach(ot_dir, pid, key)
        console.print(f"[dim]Scaffolded approach {approach.id} ({key}).[/dim]")
    elif literature and not disprove and effective_min_papers > 0:
        approach = create_approach(ot_dir, pid, "literature_map")
        console.print(
            f"[dim]Scaffolded approach {approach.id} (literature_map) — "
            "fetch preprints before proof_write.[/dim]"
        )

    mode_label = "disproof" if disprove else "proof"
    console.print(f"[bold]{mode_label.capitalize()} session[/bold] for {pid}")

    import sys

    transform = None
    if config.ui.render_math:
        from opentorus.mathtext import render_math_line

        transform = render_math_line
    indicator = ActivityIndicator(console) if sys.stdout.isatty() else None
    printer = StreamPrinter(console, transform=transform, indicator=indicator)
    llm_hooks = configure_llm_cli_hooks(
        console,
        verbose=verbose,
        debug=debug,
        indicator=indicator,
        spinner=indicator is not None,
        user_on_text=printer if (verbose or debug) else None,
    )
    trace = llm_hooks.trace
    indicator = llm_hooks.indicator
    on_llm_request = llm_hooks.on_llm_request
    on_llm_response = llm_hooks.on_llm_response
    on_thinking = llm_hooks.on_thinking
    stream_llm = llm_hooks.stream_llm
    on_text = llm_hooks.on_llm_text if (verbose or debug) else printer

    def _on_status(phase: str, detail: str | None = None) -> None:
        if trace is not None and phase == "phase" and detail:
            trace.set_banner(detail)
        elif indicator is not None:
            indicator.update(activity_label(phase, detail))

    _confirm = make_console_confirm(console, config=config)

    def _confirm_paused(decision, description, session_scope=None):
        if indicator is not None:
            indicator.pause()
        return _confirm(decision, description, session_scope)

    if literature and effective_min_papers > 0 and not (verbose or debug):
        phase = (
            "Phase 1: literature survey"
            if not disprove
            else "Phase 1: literature (context for refutation)"
        )
        console.print(f"[dim]{phase}[/dim]")
    if disprove and not (verbose or debug):
        console.print("[dim]Goal: counterexample search + refutation sketch[/dim]")

    outcome = None
    try:
        provider = get_provider(config)
        from opentorus.providers.tool_support import require_tool_calling_provider

        require_tool_calling_provider(
            provider, config, warn=lambda m: console.print(f"[yellow]{m}[/yellow]")
        )
        stream_llm = stream_llm and provider.supports_streaming
        if indicator is not None:
            indicator.update("Thinking")
        outcome = run_prove(
            root,
            ot_dir,
            provider,
            config,
            pid,
            disprove=disprove,
            literature_first=literature,
            min_papers=effective_min_papers,
            extra=note,
            confirm=_confirm_paused,
            on_text=on_text,
            on_llm_request=on_llm_request,
            on_llm_response=on_llm_response,
            stream_llm=stream_llm,
            on_thinking=on_thinking,
            on_status=_on_status,
        )
    except KeyboardInterrupt:
        from opentorus.ux import format_interrupt_message

        console.print(
            "\n[yellow]"
            + format_interrupt_message(
                f"proof session for {pid} stopped",
                resume_cmd=f"opentorus prove {pid}",
            )
            + "[/yellow]"
        )
        raise typer.Exit(code=130) from None
    except ProviderError as exc:
        from opentorus.ux import format_provider_error

        console.print(f"[red]{format_provider_error(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        if indicator is not None:
            indicator.stop()

    assert outcome is not None
    if on_llm_request is not None:
        console.print()

    if verbose or debug or not printer.streamed:
        printer.finish(outcome.answer)

    if outcome.harvested_experiments or outcome.harvested_claims:
        parts = []
        if outcome.harvested_experiments:
            parts.append(f"EXP: {', '.join(outcome.harvested_experiments)}")
        if outcome.harvested_claims:
            parts.append(f"CLAIM: {', '.join(outcome.harvested_claims)}")
        console.print(f"\n[dim]Harvested session findings into dossier ({'; '.join(parts)}).[/dim]")

    if outcome.proof_ids:
        for proof_id in outcome.proof_ids:
            proofs = store.list_proof_attempts(ot_dir, pid)
            match = next((p for p in proofs if p.id == proof_id), None)
            path = (
                f".opentorus/problems/{pid}/{match.body_path}" if match and match.body_path else "?"
            )
            gaps = len(match.gaps) if match else 0
            console.print(
                f"\n[green]{proof_id}[/green] written → {path} "
                f"({gaps} gap(s) recorded; status sketch — not formally_verified)"
            )
        if outcome.gaps_remaining > 0:
            if outcome.gap_fill_exhausted:
                console.print(
                    f"[yellow]{outcome.gaps_remaining} gap(s) still open after "
                    f"gap-fill step budget — re-run `opentorus prove {pid}` or fill "
                    f"gaps manually.[/yellow]"
                )
            else:
                console.print(
                    f"[dim]{outcome.gaps_remaining} gap(s) remain on the latest PROOF-* — "
                    "prove stopped early.[/dim]"
                )
    else:
        console.print(
            "\n[yellow]No new PROOF-* artifact.[/yellow] "
            "The agent stopped without calling proof_write "
            "(proof_write / claims alone are not enough)."
        )
        if literature and effective_min_papers > 0 and not outcome.literature_tools_used:
            console.print(
                "[yellow]Literature phase skipped — ensure permissions.mode=trusted "
                "for paper_fetch.[/yellow]"
            )
        elif literature and effective_min_papers > 0 and not outcome.literature_complete:
            console.print(
                f"[yellow]Literature requirements incomplete:[/yellow] {outcome.literature_detail}"
            )

    if outcome.proof_warnings:
        console.print("[yellow]Proof sketch warnings:[/yellow]")
        for warn in outcome.proof_warnings:
            console.print(f"  • {warn}")

    lit_summary = ""
    if outcome.papers_added:
        lit_summary = f"Papers added: {outcome.papers_added}. "
    if outcome.papers_read:
        lit_summary += f"Papers parsed: {outcome.papers_read}. "
    elif outcome.literature_tools_used:
        lit_summary += "Literature tools used. "
    if outcome.unread_papers:
        console.print(
            f"[yellow]Unread PDFs (re-fetch or run paper read-unread): "
            f"{', '.join(outcome.unread_papers)}[/yellow]"
        )
    console.print(
        f"\n[dim]{lit_summary}Tool calls: {outcome.tool_calls}. "
        "Review with: opentorus problem show "
        f"{pid} ; opentorus problem report {pid} --lint[/dim]"
    )
    if outcome.referee_verdict == "block":
        console.print(f"[red]Referee verdict: BLOCK[/red] — see `opentorus problem referee {pid}`.")

    if outcome.lint_issues:
        # The autonomous path must not pass overclaiming language silently. Regenerate
        # the report once (artifacts may have changed) and re-lint; if warnings remain,
        # gate with a non-zero exit so a script/CI run does not treat it as clean.
        from opentorus.research.dossier.report import build_report, lint_dossier_report

        try:
            build_report(ot_dir, pid)
        except OpenTorusError:
            pass
        remaining = lint_dossier_report(ot_dir, pid)
        if remaining:
            console.print(
                f"[red]Report honesty linter: {len(remaining)} unresolved warning(s).[/red] "
                f"The report overclaims relative to its artifacts; fix the wording or back the "
                f"claims, then re-run. See `opentorus problem report {pid} --lint`."
            )
            raise typer.Exit(code=1)
        console.print("[green]Report honesty linter: clean after regeneration.[/green]")


@app.command("doctor")
def doctor_cmd() -> None:
    """Check workspace, config, model provider, index, and tools."""
    from opentorus.doctor import doctor_for_cwd

    root, _ot_dir, checks = doctor_for_cwd()
    if root is None:
        for check in checks:
            console.print(f"[red]✗[/red] {check.name}: {check.detail}")
        raise typer.Exit(code=1)
    for check in checks:
        mark = "[green]✓[/green]" if check.ok else "[red]✗[/red]"
        console.print(f"{mark} {check.name}: {check.detail}")
    if not all(c.ok for c in checks):
        raise typer.Exit(code=1)


@app.command("explain")
def explain_cmd(
    artifact_id: str = typer.Argument(..., help="Artifact id, e.g. CLAIM-0001."),
) -> None:
    """Trace an artifact back to its evidence and provenance subgraph (read-only)."""
    from opentorus.research.explain import explain, render_explain_text

    base = _require_workspace_dir()
    result = explain(base, artifact_id)
    console.print(render_explain_text(result))


@app.command("dashboard")
def dashboard_cmd(
    out: str | None = typer.Option(None, "--out", help="Output HTML path."),
) -> None:
    """Export a static, read-only dashboard (graph + claims + journal)."""
    from opentorus.research.explain import export_dashboard

    base = _require_workspace_dir()
    path = export_dashboard(base, Path(out) if out else None)
    console.print(f"[green]Wrote read-only dashboard[/green] {path}")


@app.command()
def check(
    only: str | None = typer.Option(
        None, "--only", help="Run a single gate: test, lint, or typecheck."
    ),
) -> None:
    """Run the configured quality gates (test/lint/typecheck) and summarize."""
    from opentorus.quality import run_checks

    ot_dir = _require_workspace_dir()
    root = ot_dir.parent
    config = _load_workspace_config(ot_dir)
    results = run_checks(root, ot_dir, config, only=[only] if only else None)

    table = Table(title="Quality gates")
    table.add_column("Gate", style="bold")
    table.add_column("Result")
    table.add_column("Command")
    any_failed = False
    for result in results:
        if result.skipped:
            outcome = "[dim]skipped (not configured)[/dim]"
        elif result.ok:
            outcome = "[green]passed[/green]"
        else:
            outcome = f"[red]failed (exit {result.exit_code})[/red]"
            any_failed = True
        table.add_row(result.name, outcome, result.command or "[dim]—[/dim]")
    console.print(table)

    for result in results:
        if not result.skipped and not result.ok and result.stderr_summary:
            console.print(f"\n[red]{result.name} stderr:[/red]\n{result.stderr_summary}")
    if any_failed:
        raise typer.Exit(code=1)


@app.command()
def actions(
    limit: int = typer.Option(10, "--limit", "-n", help="Show the last N actions."),
) -> None:
    """Show recent tool actions from the action log."""
    base = _require_workspace_dir()
    entries = list_actions(base, limit=limit)
    if not entries:
        console.print("[dim]No actions logged yet.[/dim]")
        return
    table = Table(title="Recent actions")
    table.add_column("ID", style="bold")
    table.add_column("Tool")
    table.add_column("Status")
    for entry in entries:
        status_text = "[green]ok[/green]" if entry.ok else "[red]failed[/red]"
        table.add_row(entry.id, entry.tool_name, status_text)
    console.print(table)


@app.command("suggest")
def suggest_cmd(
    limit: int = typer.Option(6, "--limit", "-n", help="Maximum suggestions to show."),
) -> None:
    """Suggest concrete next commands based on your workspace (beginner guide)."""
    from opentorus.suggest import suggest_for_cwd

    _root, _ot, items = suggest_for_cwd(limit=limit)
    if not items:
        console.print("[dim]No suggestions right now.[/dim]")
        return
    table = Table(title="Suggested next steps", show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=3)
    table.add_column("Command", style="cyan")
    table.add_column("Why")
    for index, item in enumerate(items, start=1):
        table.add_row(str(index), item.command, item.reason)
    console.print(table)
    console.print(
        "[dim]Tip: run any command above in this terminal, or type "
        "`/suggest` inside `opentorus chat`.[/dim]"
    )


@app.command()
def init(
    problem: str = typer.Option(
        "",
        "--problem",
        help="Create a single-problem workspace seeded with this statement (becomes active).",
    ),
) -> None:
    """Initialize a ``.opentorus/`` workspace in the current directory."""
    try:
        created = init_workspace(Path.cwd())
    except OpenTorusError as exc:
        console.print(f"[red]Could not initialize workspace:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if created:
        console.print(
            f"[green]Initialized OpenTorus workspace[/green] ({len(created)} paths created)."
        )
    else:
        console.print("[yellow]Workspace already initialized[/yellow] — nothing to do.")
    console.print(f"Workspace memory lives in [bold].opentorus/[/bold] under {Path.cwd()}.")
    if problem.strip():
        # Single-problem workspace: one dossier, immediately active, so the user
        # never needs `problem new`/`use` (the README's "one problem" model).
        from opentorus.research.dossier import store

        ot_dir = _require_workspace_dir()
        dossier = store.create_dossier(ot_dir, problem.strip())
        console.print(f"[green]{dossier.id}[/green] created and set active — {dossier.title}")
        console.print(f"[dim]Next: opentorus prove (operates on {dossier.id} by default)[/dim]")
        return
    from opentorus.suggest import suggest_for_cwd

    _root, _ot, items = suggest_for_cwd(limit=3)
    if items:
        console.print("\n[bold]Suggested next steps:[/bold]")
        for item in items:
            console.print(f"  [cyan]{item.command}[/cyan]")
            console.print(f"    [dim]{item.reason}[/dim]")
        console.print("[dim]More: opentorus suggest[/dim]")


@app.command()
def status() -> None:
    """Show the current workspace, git, and project state."""
    snap = gather_status()

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Current dir", snap.cwd)
    table.add_row("Workspace root", snap.workspace_root or "[dim]none (run `opentorus init`)[/dim]")
    table.add_row("Initialized", "yes" if snap.initialized else "no")
    table.add_row("Git branch", snap.git_branch or "[dim]n/a[/dim]")
    if snap.git_dirty is not None:
        table.add_row("Git state", "dirty" if snap.git_dirty else "clean")
    table.add_row("Project mode", snap.project_mode or "[dim]n/a[/dim]")
    table.add_row("Style", snap.operating_style or "[dim]n/a[/dim]")
    table.add_row("Permission mode", snap.permission_mode or "[dim]n/a[/dim]")
    table.add_row("Claims", str(snap.num_claims))
    table.add_row("Experiments", str(snap.num_experiments))
    table.add_row("Actions", str(snap.num_actions))
    table.add_row("Evidence", str(snap.num_evidence))
    if snap.workspace_root:
        from opentorus.research.dossier import store
        from opentorus.workspace import workspace_dir

        active = store.get_active_problem(workspace_dir(Path(snap.workspace_root)))
        if active:
            table.add_row("Active problem", active)

    console.print(f"[bold]{BANNER}[/bold] status")
    console.print(table)
    console.print("[dim]Not sure what to run next? Try[/dim] [cyan]opentorus suggest[/cyan]")
