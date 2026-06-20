"""Execution backend protocol and request model (Milestone 55).

An :class:`ExecutionRequest` describes *what* to run (a logical command, a
working directory, an optional pinned image, mounts, env, network, and resource
limits). An :class:`ExecutionBackend` decides *where* it runs (host, Docker,
Podman, Apptainer) while returning the same :class:`ShellResult` shape as
``run_shell`` so callers are unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from opentorus.tools.shell import ShellResult

DEFAULT_EXEC_TIMEOUT = 120
WORKDIR_TARGET = "/work"
_WORKDIR_TARGET = WORKDIR_TARGET


class RunLimits(BaseModel):
    """Resource limits for a single execution."""

    timeout: int = DEFAULT_EXEC_TIMEOUT
    memory: str | None = None  # e.g. "2g" (container backends only)
    cpus: str | None = None  # e.g. "2" (container backends only)


class Mount(BaseModel):
    """A host path bound into the container."""

    source: str
    target: str
    read_only: bool = True


class ExecutionRequest(BaseModel):
    """A backend-neutral description of one command to execute."""

    command: str
    workdir: Path
    image: str | None = None
    mounts: list[Mount] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    network: bool = False
    limits: RunLimits = Field(default_factory=RunLimits)

    model_config = {"arbitrary_types_allowed": True}


def sandboxed_mounts(
    workdir: Path | str, *, writable_subdir: str | None = "results"
) -> list[Mount]:
    """Least-privilege mounts: workspace read-only, one writable results subdir.

    The container becomes the policy boundary — it cannot mutate the workspace
    except through the dedicated writable directory.
    """
    work = Path(workdir)
    mounts = [Mount(source=str(work), target=_WORKDIR_TARGET, read_only=True)]
    if writable_subdir:
        mounts.append(
            Mount(
                source=str(work / writable_subdir),
                target=f"{_WORKDIR_TARGET}/{writable_subdir}",
                read_only=False,
            )
        )
    return mounts


@runtime_checkable
class ExecutionBackend(Protocol):
    """A runtime that can execute an :class:`ExecutionRequest`."""

    name: str
    requires_image: bool

    def is_available(self) -> bool:
        """Whether this runtime is installed and usable."""
        ...

    def version(self) -> str | None:
        """Runtime version string, or ``None`` if unavailable."""
        ...

    def build_argv(self, request: ExecutionRequest) -> list[str]:
        """Assemble the concrete argv used to run ``request`` (testable, no exec)."""
        ...

    def run(self, request: ExecutionRequest) -> ShellResult:
        """Execute ``request`` and return its result."""
        ...
