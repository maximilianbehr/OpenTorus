"""OpenTorus CLI — env commands (split from the former monolithic cli.py)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _load_workspace_config,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.errors import OpenTorusError

env_app = typer.Typer(cls=SortedGroup, help="Inspect tool execution environments and backends.")
app.add_typer(env_app, name="env")


@env_app.command("list")
def env_list() -> None:
    """Show configured tool environments, their runtime, and availability."""
    from opentorus.execution import list_environments, select_backend

    base = _require_workspace_dir()
    config = _load_workspace_config(base)
    environments = list_environments(base)

    console.print(f"[dim]Execution backend: {config.execution.backend}[/dim]")
    table = Table(title="Tool environments")
    table.add_column("Name", style="bold")
    table.add_column("Image")
    table.add_column("License")
    table.add_column("Runtime")
    table.add_column("Available")
    for name in sorted(environments):
        env = environments[name]
        if env.license == "proprietary":
            image = "[yellow]bring your own[/yellow]"
            available = "[yellow]BYO image/license[/yellow]"
            runtime = "—"
        elif env.image:
            image = env.image
            backend = select_backend(config, needs_image=True)
            runtime = backend.name
            ok = backend.is_available() and backend.requires_image
            available = "[green]yes[/green]" if ok else "[red]no runtime[/red]"
        else:
            image = "[dim]not prepared[/dim]"
            available = "[yellow]env prepare --file …[/yellow]"
            runtime = "—"
        table.add_row(name, image, env.license, runtime, available)
    console.print(table)
    console.print(
        "[dim]OpenTorus does not ship container images. "
        "Run: opentorus env prepare python-sci --file docker/Dockerfile[/dim]"
    )
    console.print(
        "[dim]Proprietary tools (Matlab/Mathematica) need your own image and license.[/dim]"
    )


@env_app.command("prepare")
def env_prepare(
    name: str = typer.Argument(..., help="Environment name, e.g. python-sci or a custom stack."),
    rebuild: bool = typer.Option(False, "--rebuild", help="Force a fresh container build."),
    file: Path | None = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to Dockerfile or Containerfile (relative to workspace root).",
        exists=True,
        dir_okay=True,
        readable=True,
    ),
    context: Path | None = typer.Option(
        None,
        "--context",
        "-C",
        help="Build context directory (default: parent directory of --file).",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
    ),
    tag: str | None = typer.Option(
        None,
        "--tag",
        help="Local image tag (default: opentorus-NAME:local).",
    ),
    command: str | None = typer.Option(
        None,
        "--command",
        help="Default command for exp_new in this environment.",
    ),
) -> None:
    """Build a user-supplied container image and wire the workspace to it.

    Requires ``--file path/to/Dockerfile`` on first use. OpenTorus does not
    ship container images. Paths are saved for later ``--rebuild`` runs.
    Requires Docker or Podman.
    """
    from opentorus.execution.prepare import prepare_environment

    base = _require_workspace_dir()
    try:
        result = prepare_environment(
            base,
            name,
            rebuild=rebuild,
            containerfile=file,
            build_context=context,
            image_tag=tag,
            default_command=command,
        )
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    action = "Built" if result.built else "Reused"
    console.print(
        f"[green]{action}[/green] {result.image} via {result.runtime} "
        f"→ {result.config_path.relative_to(base.parent)}"
    )
    if result.containerfile is not None:
        console.print(f"[dim]Containerfile: {result.containerfile}[/dim]")
    console.print(
        "[dim]Use exp_new(..., environment='"
        + name
        + "') then exp_run. execution.backend=auto is enough when Docker/Podman is installed.[/dim]"
    )


@env_app.command("verify")
def env_verify() -> None:
    """Fail if any shipped environment is not digest-pinned (reproducibility)."""
    from opentorus.execution.pinning import unpinned_environments

    base = _require_workspace_dir()
    unpinned = unpinned_environments(base)
    if not unpinned:
        console.print("[green]All shipped environments are digest-pinned.[/green]")
        return
    for env in sorted(unpinned, key=lambda e: e.name):
        console.print(f"[red]unpinned[/red] {env.name}: {env.image}")
    console.print("[yellow]Pin each with 'opentorus env pin <name> sha256:<digest>'.[/yellow]")
    raise typer.Exit(code=1)


@env_app.command("pin")
def env_pin(
    name: str = typer.Argument(..., help="Environment name, e.g. julia."),
    digest: str = typer.Argument(..., help="Image digest, e.g. sha256:<64 hex>."),
) -> None:
    """Pin an environment's image to an immutable digest in the workspace."""
    from opentorus.execution.pinning import pin_environment

    base = _require_workspace_dir()
    try:
        env = pin_environment(base, name, digest)
    except OpenTorusError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Pinned[/green] {name} → {env.image}")
