"""Select an execution backend from config (Milestone 55).

``auto`` prefers the host for plain commands; when a pinned image is requested it
picks the first available container runtime in ``config.execution.auto_preference``
order, falling back to the host (with a note) if none is installed. An explicit
backend is returned as-is, even if unavailable, so the caller can report honestly.
"""

from __future__ import annotations

from opentorus.config import Config
from opentorus.execution.backends import (
    ApptainerBackend,
    DockerBackend,
    LocalBackend,
    PodmanBackend,
)
from opentorus.execution.base import ExecutionBackend

_CONTAINER_BACKENDS: dict[str, type] = {
    "docker": DockerBackend,
    "podman": PodmanBackend,
    "apptainer": ApptainerBackend,
}
_REMOTE_BACKENDS = ("ssh", "slurm")


def _make_remote(name: str, config: Config) -> ExecutionBackend:
    from opentorus.execution.remote import RemoteBackend, SlurmBackend

    remote = config.execution.remote
    common = {
        "host": remote.host,
        "user": remote.user,
        "remote_root": remote.remote_root,
        "ssh_command": remote.ssh_command,
        "copy_command": remote.copy_command,
    }
    if name == "ssh":
        return RemoteBackend(**common)  # type: ignore[arg-type]
    return SlurmBackend(
        partition=remote.partition,
        time_limit=remote.time_limit,
        account=remote.account,
        extra_sbatch=remote.extra_sbatch,
        **common,
    )


def make_backend(name: str, config: Config | None = None) -> ExecutionBackend:
    """Instantiate a backend by name (``local``, a container, or a remote runtime)."""
    if name == "local":
        return LocalBackend()
    if name in _REMOTE_BACKENDS:
        if config is None:
            raise ValueError(
                f"Remote backend '{name}' requires a config to read connection settings."
            )
        return _make_remote(name, config)
    cls = _CONTAINER_BACKENDS.get(name)
    if cls is None:
        raise ValueError(f"Unknown execution backend '{name}'.")
    return cls()


def available_backends(config: Config) -> dict[str, ExecutionBackend]:
    """Return all installed backends, keyed by name (``local`` always present)."""
    found: dict[str, ExecutionBackend] = {"local": LocalBackend()}
    for name in _CONTAINER_BACKENDS:
        backend = make_backend(name)
        if backend.is_available():
            found[name] = backend
    return found


def select_backend(config: Config, *, needs_image: bool = False) -> ExecutionBackend:
    """Resolve the backend to use for this run.

    An explicit (non-auto) choice is honoured verbatim. ``auto`` returns the host
    for plain commands, or the first available container runtime when an image is
    needed, falling back to the host if none is installed.
    """
    choice = config.execution.backend
    if choice != "auto":
        return make_backend(choice, config)

    if not needs_image:
        return LocalBackend()

    for name in config.execution.auto_preference:
        if name in _CONTAINER_BACKENDS:
            backend = make_backend(name)
            if backend.is_available():
                return backend
    return LocalBackend()
