"""Tool-environment registry (Milestone 56).

A *tool environment* names a runtime once and pins it by digest, so an experiment
can declare ``environment: julia`` and the runner resolves it to an image and a
default command. Free, redistributable stacks ship as built-in defaults; users
extend or override via ``environments.yaml`` at the user level
(``~/.opentorus/environments.yaml``) or the workspace level
(``.opentorus/environments.yaml``). Proprietary tools (Mathematica, Matlab) are
bring-your-own: declared but never bundled with an image (Milestone 57).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from opentorus.errors import OpenTorusError

LicenseKind = Literal["open", "proprietary"]

ENVIRONMENTS_FILENAME = "environments.yaml"


class ToolEnvironment(BaseModel):
    """A named, pinned runtime for a tool stack."""

    name: str
    image: str | None = None  # digest-pinned OCI ref; None ⇒ bring-your-own
    default_command: str = "python run.py"
    kind: str = "generic"
    license: LicenseKind = "open"
    license_env: str | None = None  # e.g. "MLM_LICENSE_FILE" for Matlab
    notes: str = ""
    # Optional local-build metadata (``opentorus env prepare``). Paths are relative
    # to the workspace root unless absolute.
    build_context: str | None = None
    containerfile: str | None = None

    @property
    def is_bring_your_own(self) -> bool:
        return self.license == "proprietary" or not self.image


# Named runtime profiles — no images are shipped; users build their own via
# ``opentorus env prepare NAME --file path/to/Dockerfile``.
_BUILTIN: dict[str, ToolEnvironment] = {
    env.name: env
    for env in [
        ToolEnvironment(
            name="python-sci",
            image=None,
            default_command="python run.py",
            kind="python",
            notes=(
                "User-built Python stack. Run: opentorus env prepare python-sci "
                "--file docker/Dockerfile"
            ),
        ),
        ToolEnvironment(
            name="julia",
            image=None,
            default_command="julia run.jl",
            kind="julia",
            notes=(
                "User-built Julia stack. Run: opentorus env prepare julia --file docker/Dockerfile"
            ),
        ),
        ToolEnvironment(
            name="rust",
            image=None,
            default_command="bash run.sh",
            kind="rust",
            notes="User-built Rust stack. Run: opentorus env prepare rust --file docker/Dockerfile",
        ),
        ToolEnvironment(
            name="cpp",
            image=None,
            default_command="bash run.sh",
            kind="cpp",
            notes="User-built C/C++ stack. Run: opentorus env prepare cpp --file docker/Dockerfile",
        ),
        ToolEnvironment(
            name="macaulay2",
            image=None,
            default_command="M2 --script run.m2",
            kind="cas",
            notes=(
                "User-built Macaulay2 stack. Run: opentorus env prepare macaulay2 "
                "--file docker/Dockerfile"
            ),
        ),
        # Proprietary, bring-your-own: no image is shipped.
        ToolEnvironment(
            name="matlab",
            image=None,
            default_command="matlab -batch run",
            kind="proprietary",
            license="proprietary",
            license_env="MLM_LICENSE_FILE",
            notes="Bring your own MathWorks image and license server.",
        ),
        ToolEnvironment(
            name="mathematica",
            image=None,
            default_command="wolframscript -file run.wl",
            kind="proprietary",
            license="proprietary",
            license_env="MATHEMATICA_LICENSE",
            notes="Bring your own Wolfram image and license.",
        ),
    ]
}


def _load_file(path: Path) -> dict[str, ToolEnvironment]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise OpenTorusError(f"Could not read environments at '{path}': {exc}") from exc
    entries = raw.get("environments", raw) if isinstance(raw, dict) else {}
    result: dict[str, ToolEnvironment] = {}
    if isinstance(entries, list):
        for item in entries:
            env = ToolEnvironment.model_validate(item)
            result[env.name] = env
    elif isinstance(entries, dict):
        for name, item in entries.items():
            data = {"name": name, **(item or {})}
            env = ToolEnvironment.model_validate(data)
            result[env.name] = env
    return result


def _user_environments_path() -> Path:
    return Path.home() / ".opentorus" / ENVIRONMENTS_FILENAME


def _workspace_environments_path(ot_dir: Path) -> Path:
    return ot_dir / ENVIRONMENTS_FILENAME


def list_environments(ot_dir: Path) -> dict[str, ToolEnvironment]:
    """Built-ins overlaid by user-level, then workspace-level overrides."""
    merged: dict[str, ToolEnvironment] = dict(_BUILTIN)
    merged.update(_load_file(_user_environments_path()))
    merged.update(_load_file(_workspace_environments_path(ot_dir)))
    return merged


def resolve_environment(ot_dir: Path, name: str) -> ToolEnvironment:
    """Resolve an environment by name, raising clearly if unknown."""
    envs = list_environments(ot_dir)
    env = envs.get(name)
    if env is None:
        valid = ", ".join(sorted(envs)) or "(none)"
        raise OpenTorusError(f"Unknown tool environment '{name}'. Known: {valid}")
    return env
