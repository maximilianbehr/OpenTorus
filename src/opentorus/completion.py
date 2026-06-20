"""Shell autocompletion helpers for the OpenTorus CLI."""

from __future__ import annotations

import types
from pathlib import Path
from typing import TypeGuard, Union, get_args, get_origin

import typer
from pydantic import BaseModel

from opentorus.config import Config

# Known enum-like config values for value completion after ``config set KEY``.
_CONFIG_VALUE_CHOICES: dict[str, list[str]] = {
    "agent.style": ["cautious", "normal", "fast", "autonomous"],
    "agent.mode": ["normal", "review"],
    "permissions.mode": ["safe", "ask", "trusted"],
    "project.mode": ["code", "research", "writing", "data", "mixed"],
    "model.provider": ["mock", "openai", "anthropic", "ollama"],
}

_SHELLS = ("bash", "zsh", "fish", "powershell")


def completion_script(shell: str, prog_name: str = "opentorus") -> str:
    """Return a shell completion script for ``prog_name``."""
    from typer._completion_shared import get_completion_script

    complete_var = f"_{prog_name.replace('-', '_').upper()}_COMPLETE"
    return get_completion_script(prog_name=prog_name, complete_var=complete_var, shell=shell)


def install_completion(shell: str, prog_name: str = "opentorus") -> Path:
    """Write completion into the user's shell config; returns the target path."""
    from typer._completion_shared import install

    installed_shell, path = install(shell=shell, prog_name=prog_name)
    return path


def _is_model_type(annotation: object) -> TypeGuard[type[BaseModel]]:
    try:
        return isinstance(annotation, type) and issubclass(annotation, BaseModel)
    except TypeError:
        return False


def _unwrap_annotation(annotation: object) -> object:
    # Only unwrap Optional/Union (e.g. ``Model | None``) to its inner type. A
    # container like ``list[McpServerConfig]`` is NOT a dotted-settable section, so
    # do not descend into it (else we'd advertise unsettable keys like
    # ``tools.mcp.command`` that ``config set`` rejects).
    origin = get_origin(annotation)
    if origin is Union or origin is getattr(types, "UnionType", None):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if args:
            return args[0]
    return annotation


def dotted_config_keys(model: type[BaseModel], prefix: str = "") -> list[str]:
    """All dotted keys accepted by ``opentorus config set``."""
    keys: list[str] = []
    for name, field in model.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        inner = _unwrap_annotation(field.annotation)
        if _is_model_type(inner):
            keys.extend(dotted_config_keys(inner, path))
        else:
            keys.append(path)
    return sorted(keys)


def _match(prefix: str, options: list[str]) -> list[str]:
    if not prefix:
        return options
    return [option for option in options if option.startswith(prefix)]


def complete_shell_name(
    ctx: typer.Context,  # noqa: ARG001
    incomplete: str,
) -> list[str]:
    return _match(incomplete, list(_SHELLS))


def complete_config_key(
    ctx: typer.Context,  # noqa: ARG001
    incomplete: str,
) -> list[str]:
    return _match(incomplete, dotted_config_keys(Config))


def complete_config_value(
    ctx: typer.Context,
    incomplete: str,
) -> list[str]:
    key = str(ctx.params.get("key") or "")
    if "=" in key and ctx.params.get("value") is None:
        key, _, _ = key.partition("=")
    choices = _CONFIG_VALUE_CHOICES.get(key.strip())
    if not choices:
        return []
    return _match(incomplete, choices)
