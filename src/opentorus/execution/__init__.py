"""Pluggable execution backends (Phase 18, Milestone 55).

Decouples *what* runs from *where*: experiments and tool commands target the host
or a container runtime (Docker / Podman / Apptainer) through one neutral
interface, with safe defaults (no network, least-privilege mounts) and honest
reporting when a requested runtime is unavailable.
"""

from opentorus.execution.backends import (
    ApptainerBackend,
    DockerBackend,
    LocalBackend,
    PodmanBackend,
)
from opentorus.execution.base import (
    ExecutionBackend,
    ExecutionRequest,
    Mount,
    RunLimits,
    sandboxed_mounts,
)
from opentorus.execution.environments import (
    ToolEnvironment,
    list_environments,
    resolve_environment,
)
from opentorus.execution.pinning import (
    image_digest,
    is_digest_pinned,
    pin_environment,
    resolve_and_pin,
    unpinned_environments,
    verify_pinned,
)
from opentorus.execution.prepare import PrepareResult, local_image_tag, prepare_environment
from opentorus.execution.registry import (
    available_backends,
    make_backend,
    select_backend,
)

__all__ = [
    "ExecutionBackend",
    "ExecutionRequest",
    "Mount",
    "RunLimits",
    "sandboxed_mounts",
    "ToolEnvironment",
    "list_environments",
    "resolve_environment",
    "LocalBackend",
    "DockerBackend",
    "PodmanBackend",
    "ApptainerBackend",
    "available_backends",
    "make_backend",
    "select_backend",
    "is_digest_pinned",
    "image_digest",
    "unpinned_environments",
    "verify_pinned",
    "pin_environment",
    "resolve_and_pin",
    "PrepareResult",
    "local_image_tag",
    "prepare_environment",
]
