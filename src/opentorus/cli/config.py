"""OpenTorus CLI — config commands (split from the former monolithic cli.py)."""

from __future__ import annotations

import typer

from opentorus.cli._base import (
    SortedGroup,
    _load_workspace_config,
    _require_workspace_dir,
    app,
    console,
)
from opentorus.completion import (
    complete_config_key,
    complete_config_value,
)
from opentorus.config import CONFIG_FILENAME

config_app = typer.Typer(cls=SortedGroup, help="Inspect and update workspace configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Print the current configuration as YAML."""
    ot_dir = _require_workspace_dir()
    config = _load_workspace_config(ot_dir)
    console.print(config.to_yaml().rstrip())


@config_app.command("set")
def config_set(
    key: str = typer.Argument(
        ...,
        help="Dotted config key, or key=value (e.g. model.num_predict=-1).",
        autocompletion=complete_config_key,
    ),
    value: str | None = typer.Argument(
        None,
        help="New value (bool/int/float/str). For negatives, use key=value or --value=-1.",
        autocompletion=complete_config_value,
    ),
    value_option: str | None = typer.Option(
        None,
        "--value",
        help="New value when VALUE starts with '-' (e.g. --value=-1).",
    ),
) -> None:
    """Set a config value by dotted key and persist it."""
    from opentorus.config import set_dotted, write_config
    from opentorus.errors import ConfigError

    if value is None and value_option is None and "=" in key:
        key, _, value = key.partition("=")

    actual = value_option if value_option is not None else value
    if actual is None:
        console.print(
            "[red]Missing value.[/red] Provide VALUE, key=value, or --value=… "
            "(for negatives: `opentorus config set model.num_predict=-1` "
            "or `opentorus config set model.num_predict --value=-1`)."
        )
        raise typer.Exit(code=1)

    ot_dir = _require_workspace_dir()
    config = _load_workspace_config(ot_dir)
    try:
        updated = set_dotted(config, key, actual)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    write_config(ot_dir / CONFIG_FILENAME, updated)
    # Verify the write round-trips: a "Set" message with nothing persisted once let a
    # whole run execute with a gate its driver believed it had enabled. Never report
    # success on the strength of the in-memory update alone.
    from opentorus.config import load_config

    persisted = load_config(ot_dir / CONFIG_FILENAME).model_dump(mode="json")
    expected = updated.model_dump(mode="json")
    path_parts = key.split(".")
    node_p: object = persisted
    node_e: object = expected
    for part in path_parts:
        node_p = node_p.get(part) if isinstance(node_p, dict) else None
        node_e = node_e.get(part) if isinstance(node_e, dict) else None
    if node_p != node_e:
        console.print(
            f"[red]Failed to persist {key}: the written config re-reads as "
            f"{node_p!r} instead of {node_e!r}. The config file may predate this "
            "field and lack its section — please report this.[/red]"
        )
        raise typer.Exit(code=1)
    console.print(f"[green]Set[/green] {key} = {actual}")
