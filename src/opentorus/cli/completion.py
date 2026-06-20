"""OpenTorus CLI — completion commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer

from opentorus.cli._base import (
    SortedGroup,
    app,
    console,
)
from opentorus.completion import (
    complete_shell_name,
    completion_script,
    install_completion,
)

completion_app = typer.Typer(cls=SortedGroup, help="Shell tab-completion helpers.")
app.add_typer(completion_app, name="completion")


@completion_app.command("show")
def completion_show(
    shell: str = typer.Argument(
        "zsh",
        help="Shell name: bash, zsh, fish, or powershell.",
        autocompletion=complete_shell_name,
    ),
) -> None:
    """Print a completion script for eval or manual installation."""
    from opentorus.completion import _SHELLS

    if shell not in _SHELLS:
        console.print(f"[red]Unknown shell '{shell}'.[/red] Choose from: {', '.join(_SHELLS)}")
        raise typer.Exit(code=1)
    typer.echo(completion_script(shell))


@completion_app.command("install")
def completion_install(
    shell: str = typer.Argument(
        "zsh",
        help="Shell name: bash, zsh, fish, or powershell.",
        autocompletion=complete_shell_name,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print instructions only; do not write to shell config.",
    ),
) -> None:
    """Install TAB completion for ``opentorus`` subcommands and config keys."""
    from opentorus.completion import _SHELLS

    if shell not in _SHELLS:
        console.print(f"[red]Unknown shell '{shell}'.[/red] Choose from: {', '.join(_SHELLS)}")
        raise typer.Exit(code=1)
    if dry_run:
        console.print("[bold]One-time install[/bold] (writes to your shell config, then restart):")
        console.print(f"  opentorus completion install {shell}")
        console.print("[bold]Current session only[/bold] (until you close the terminal):")
        console.print(f'  eval "$(opentorus completion show {shell})"')
        console.print(
            "[dim]After install, TAB completes subcommands (e.g. opentorus prob↹) and "
            "config keys/values (e.g. opentorus config set agent.style aut↹ → autonomous).[/dim]"
        )
        return
    try:
        path = install_completion(shell)
    except SystemExit as exc:
        raise typer.Exit(code=exc.code if isinstance(exc.code, int) else 1) from exc
    console.print(f"[green]{shell} completion installed in {path}[/green]")
    console.print("Restart the terminal (or run `exec zsh`) for TAB completion to take effect.")
