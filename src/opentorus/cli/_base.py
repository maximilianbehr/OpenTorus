"""OpenTorus command-line interface.

The interactive session (Milestone 2) is the primary UX; scripting subcommands
(``init``, ``status``, ``memory``, ``actions``, ...) layer on top of the same
workspace primitives.
"""

from __future__ import annotations

from pathlib import Path

import typer
from typer.core import TyperGroup

from opentorus import __version__
from opentorus.config import CONFIG_FILENAME, Config, default_config, load_config
from opentorus.errors import OpenTorusError
from opentorus.paths import (
    find_workspace_root,
    looks_like_uninitialized_project,
    resolve_cli_workspace_root,
)
from opentorus.ux import make_console
from opentorus.workspace import workspace_dir

BANNER = "◎ OpenTorus"
SLOGAN = "An AI agent for open mathematical problems — honest by design."

console = make_console()


def _cli_verbosity(ctx: typer.Context) -> tuple[bool, bool]:
    obj = getattr(ctx, "obj", None) or {}
    return bool(obj.get("verbose")), bool(obj.get("debug"))


class SortedGroup(TyperGroup):
    """Typer group that lists subcommands in alphabetical order in --help."""

    def list_commands(self, ctx) -> list[str]:
        return sorted(super().list_commands(ctx))


app = typer.Typer(
    help=(
        "OpenTorus — a terminal-native agent for iterative research engineering.\n\n"
        f"{BANNER} — {SLOGAN}"
    ),
    add_completion=True,
    cls=SortedGroup,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"opentorus {__version__}")
        raise typer.Exit()


def _resolve_problem_id(ot_dir: Path, problem_id: str | None) -> str:
    """Resolve a dossier id from an explicit value or the workspace's active problem.

    Lets ``problem`` subcommands omit the id and operate on the current problem
    (set by ``problem use`` or by creating a dossier), removing the need to repeat
    ``PROBLEM-XXXX`` on every command. Raises a clear error when neither is available.
    """
    from opentorus.research.dossier import store

    if problem_id:
        pid = problem_id.strip().upper()
        return store.canonical_problem_id(pid) or pid
    active = store.get_active_problem(ot_dir)
    if active:
        return active
    raise OpenTorusError(
        "No problem given and no active problem set. Pass a PROBLEM id, or select one "
        "with `opentorus problem use PROBLEM-0001`."
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the OpenTorus version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help=(
            "Informational logs and streamed LLM request/response trace "
            "(prove, extract, problem export, run, …)."
        ),
    ),
    debug: bool = typer.Option(False, "--debug", help="Show debug logs (verbose internals)."),
    mode: str | None = typer.Option(
        None, "--mode", help="Operating mode for this session: 'normal' or 'review' (read-only)."
    ),
) -> None:
    """OpenTorus — inspectable loops for code, research, and experiments."""
    import logging

    from opentorus.dotenv import load_project_dotenv
    from opentorus.ux import setup_logging

    setup_logging(verbose=verbose, debug=debug)
    # Load a project .env so provider API keys (OPENAI_API_KEY, …) are picked up
    # without an explicit shell export; never overrides an already-set variable.
    loaded = load_project_dotenv()
    if loaded:
        logging.getLogger("opentorus").debug("Loaded .env variables: %s", ", ".join(loaded))
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug
    if mode is not None:
        if mode not in ("normal", "review"):
            console.print(f"[red]Unknown mode '{mode}'.[/red] Valid modes: normal, review.")
            raise typer.Exit(code=1)
        global _MODE_OVERRIDE
        _MODE_OVERRIDE = mode
    if ctx.invoked_subcommand is not None:
        return
    # Bare ``opentorus`` launches the interactive session.
    from opentorus.repl import run_repl

    run_repl(console=console)


def _require_workspace_root() -> Path:
    cwd = Path.cwd().resolve()
    root = resolve_cli_workspace_root(cwd)
    if root is None:
        if looks_like_uninitialized_project(cwd):
            console.print(
                "[red]No `.opentorus/` in this directory[/red] (found `papers/`). "
                f"Run [bold]opentorus init[/bold] in [bold]{cwd}[/bold] first."
            )
        elif find_workspace_root(cwd) == Path.home().resolve() and cwd != Path.home().resolve():
            console.print(
                "[red]No OpenTorus workspace in this directory.[/red] "
                f"Run [bold]opentorus init[/bold] in [bold]{cwd}[/bold] "
                "(a workspace in `$HOME` does not apply to subfolders)."
            )
        else:
            console.print(
                "[red]No OpenTorus workspace in this directory.[/red] "
                f"Run [bold]opentorus init[/bold] in [bold]{cwd}[/bold] first."
            )
        raise typer.Exit(code=1)
    return root


def _require_workspace_dir() -> Path:
    return workspace_dir(_require_workspace_root())


# Session-scoped override set by the global ``--mode`` flag (e.g. ``--mode review``).
_MODE_OVERRIDE: str | None = None


def _load_workspace_config(ot_dir: Path) -> Config:
    config_path = ot_dir / CONFIG_FILENAME
    config = load_config(config_path) if config_path.is_file() else default_config()
    if _MODE_OVERRIDE is not None:
        config.agent.mode = _MODE_OVERRIDE  # type: ignore[assignment]
    return config


def _build_egress_guard(ot_dir: Path, config: Config):
    """Construct a network-egress guard from config + current mode/style."""
    from opentorus.research.egress import EgressGuard

    lit = config.tools.literature

    def _confirm(host: str) -> bool:
        answer = console.input(f"Allow network request to '{host}'? [y] yes  [n] no: ")
        return answer.strip().lower() in {"y", "yes"}

    return EgressGuard(
        config.permissions.mode,
        style=config.agent.style,
        review=config.agent.mode == "review",
        rate_limit_per_minute=lit.rate_limit_per_minute,
        daily_request_budget=lit.daily_request_budget,
        confirm=_confirm,
        ledger_path=ot_dir / "egress.json",
        dlp=config.governance.dlp,
    )


def _run_problem_extraction(
    ctx: typer.Context,
    *,
    paper_id: str | None,
    from_markdown: Path | None,
    heuristic_only: bool,
    llm_only: bool,
    vision: bool,
    from_page: int | None,
    to_page: int | None,
) -> None:
    from opentorus.errors import ProviderError
    from opentorus.providers.registry import get_provider
    from opentorus.research.dossier import store
    from opentorus.research.papers import get_paper
    from opentorus.research.pdf_text import extract_pdf_pages_pypdf, is_usable_extraction
    from opentorus.research.problem_extraction import (
        extract_problems_from_markdown,
        extract_problems_from_paper,
        extraction_hints,
    )

    if paper_id and from_markdown:
        console.print("[red]Provide either PAPER-ID or --from FILE.md, not both.[/red]")
        raise typer.Exit(code=1)
    if not paper_id and from_markdown is None:
        console.print(
            "[red]Missing source.[/red] Provide a PAPER-* id or `--from path/to/file.md`."
        )
        raise typer.Exit(code=1)

    if from_markdown is not None and (vision or from_page or to_page or heuristic_only):
        if heuristic_only:
            console.print(
                "[red]--heuristic-only does not apply to markdown extraction "
                "(markdown uses the LLM only).[/red]"
            )
        elif vision or from_page or to_page:
            console.print("[red]--vision and page flags apply only to paper extraction.[/red]")
        raise typer.Exit(code=1)

    if heuristic_only and (llm_only or vision):
        console.print("[red]--heuristic-only cannot be combined with --llm-only or --vision.[/red]")
        raise typer.Exit(code=1)

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    provider = None
    llm_available = False
    if from_markdown is not None or not heuristic_only:
        try:
            provider = get_provider(config)
            llm_available = getattr(provider, "name", "mock") != "mock"
        except ProviderError:
            provider = None

    if from_markdown is not None and not llm_available:
        console.print(
            "[red]Markdown extraction needs a configured model provider[/red] "
            f"(current: {getattr(provider, 'name', 'mock')}). "
            "Set one with `opentorus config set model.provider ollama` (and model.name)."
        )
        raise typer.Exit(code=1)

    if (llm_only or vision) and not llm_available:
        flag = "--vision" if vision else "--llm-only"
        console.print(
            f"[red]{flag} needs a configured model provider[/red] (current: "
            f"{getattr(provider, 'name', 'mock')}). Set one with "
            "`opentorus config set model.provider ollama` (and model.name)."
        )
        raise typer.Exit(code=1)

    scanned_pdf = False
    if paper_id:
        paper = get_paper(base, paper_id)
        if paper and paper.local_path:
            pdf_path = base / paper.local_path
            if pdf_path.is_file():
                scanned_pdf = not is_usable_extraction(extract_pdf_pages_pypdf(pdf_path))

        if vision:
            from opentorus.research.pdf_text import pdftoppm_available

            if not (paper and paper.local_path and (base / paper.local_path).is_file()):
                console.print(
                    f"[red]--vision needs a local PDF for {paper_id}.[/red] "
                    f"Fetch or add one first (`opentorus paper fetch …`)."
                )
                raise typer.Exit(code=1)
            if not pdftoppm_available():
                console.print(
                    "[red]--vision needs `pdftoppm`[/red] (from poppler) to render pages. "
                    "Install poppler (e.g. `brew install poppler`)."
                )
                raise typer.Exit(code=1)
            from opentorus.providers.vision import provider_supports_vision

            ok, detail = provider_supports_vision(provider, config)
            if not ok:
                model = config.model.name if config.model.name else "(unset)"
                console.print(
                    f"[red]--vision requires a vision-capable model[/red] "
                    f"(current: {getattr(provider, 'name', 'mock')} / {model})."
                )
                console.print(f"[yellow]{detail}[/yellow]")
                raise typer.Exit(code=1)

    from opentorus.ux import ActivityIndicator, compose_progress_label, configure_llm_cli_hooks

    verbose, debug = _cli_verbosity(ctx)
    indicator: ActivityIndicator | None = None
    on_llm_text = None
    on_llm_thinking = None
    on_llm_request = None
    on_llm_response = None
    stream_llm = False
    if llm_available and not heuristic_only:
        llm_hooks = configure_llm_cli_hooks(console, verbose=verbose, debug=debug)
        indicator = llm_hooks.indicator
        on_llm_text = llm_hooks.on_llm_text
        on_llm_thinking = llm_hooks.on_thinking
        on_llm_request = llm_hooks.on_llm_request
        on_llm_response = llm_hooks.on_llm_response
        stream_llm = llm_hooks.stream_llm
        if provider is not None:
            stream_llm = stream_llm and getattr(provider, "supports_streaming", False)

    def _progress(line: str) -> None:
        if line.startswith("  +"):
            if indicator is not None:
                indicator.pause()
            console.print(f"[green]{line}[/green]")
        elif line.startswith("["):
            if indicator is not None:
                indicator.pause()
            console.print(f"[cyan]{line}[/cyan]")
        elif line.startswith("  …"):
            console.print(f"[dim]{line}[/dim]")
        else:
            if indicator is not None:
                indicator.update(compose_progress_label(line))
            console.print(f"[bold]{line}[/bold]")

    outcome = None
    try:
        if from_markdown is not None:
            outcome = extract_problems_from_markdown(
                base,
                from_markdown,
                provider=provider,
                on_progress=_progress,
                on_llm_text=on_llm_text,
                on_llm_thinking=on_llm_thinking,
                on_llm_request=on_llm_request,
                on_llm_response=on_llm_response,
                stream_llm=stream_llm,
            )
        else:
            assert paper_id is not None
            outcome = extract_problems_from_paper(
                base,
                paper_id,
                provider=provider,
                use_llm=not heuristic_only,
                prefer_llm=llm_only,
                force_vision=vision,
                on_progress=_progress,
                on_llm_text=on_llm_text,
                on_llm_thinking=on_llm_thinking,
                on_llm_request=on_llm_request,
                on_llm_response=on_llm_response,
                stream_llm=stream_llm,
                page_from=from_page,
                page_to=to_page,
            )
    except KeyboardInterrupt:
        saved = store.list_dossiers(base)
        console.print(
            f"\n[yellow]Interrupted.[/yellow] {len(saved)} problem dossier(s) in workspace."
        )
        raise typer.Exit(code=130) from None
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        if indicator is not None:
            indicator.stop()
        if on_llm_text is not None or on_llm_request is not None:
            console.print()

    assert outcome is not None
    problems = outcome.problems
    if not problems:
        target = from_markdown.name if from_markdown else paper_id
        if from_markdown:
            console.print(
                f"[yellow]No problems extracted from {target} "
                "(model returned no candidates).[/yellow]"
            )
        else:
            console.print(f"[yellow]No open-problem headings found in {target}.[/yellow]")
        if paper_id:
            for hint in extraction_hints(
                base, paper_id, llm_available=llm_available, scanned_pdf=scanned_pdf
            ):
                console.print(f"[dim]{hint}[/dim]")
        elif not llm_available:
            console.print("[dim]Configure a model provider for LLM extraction from markdown.[/dim]")
        return

    method_label = {
        "vision": "vision model (page images)",
        "llm": "LLM",
        "heuristic": "heuristic",
        "none": "none",
    }[outcome.method]
    console.print(f"[green]Created {len(problems)} problem dossier(s) via {method_label}:[/green]")
    for problem in problems:
        console.print(f"  {problem.id}: {problem.title}")


if __name__ == "__main__":
    app()
