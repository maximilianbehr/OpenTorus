"""Concrete execution backends: local host, Docker, Podman, Apptainer.

Container backends build an explicit argv that wraps the logical command, apply
least-privilege defaults (no network unless requested, read-only workspace mount,
optional cpu/memory limits), and run it via the shared ``run_argv`` helper so the
result shape matches the rest of OpenTorus. The argv assembly is pure and tested
without invoking any real container.
"""

from __future__ import annotations

import shlex
import shutil

from opentorus.execution.base import WORKDIR_TARGET as _WORKDIR_TARGET
from opentorus.execution.base import ExecutionRequest, Mount
from opentorus.tools.shell import ShellResult, run_argv


def _which(binary: str) -> bool:
    return shutil.which(binary) is not None


def _image_ref_docker(image: str) -> str:
    return image


def _image_ref_apptainer(image: str) -> str:
    """Apptainer needs a source: a local ``.sif``/path, else a ``docker://`` ref."""
    if image.startswith(("/", "./", "../")) or image.endswith(".sif"):
        return image
    if "://" in image:
        return image
    return f"docker://{image}"


class LocalBackend:
    """Run on the host, exactly like the previous ``run_shell`` behaviour."""

    name = "local"
    requires_image = False

    def is_available(self) -> bool:
        return True

    def version(self) -> str | None:
        return "host"

    def build_argv(self, request: ExecutionRequest) -> list[str]:
        return shlex.split(request.command)

    def run(self, request: ExecutionRequest) -> ShellResult:
        return run_argv(
            self.build_argv(request),
            cwd=request.workdir,
            timeout=request.limits.timeout,
            label=request.command,
            env=request.env or None,
        )


class _OciBackend:
    """Shared argv assembly for Docker-compatible CLIs (Docker, Podman)."""

    name = "oci"
    binary = "docker"
    requires_image = True

    def is_available(self) -> bool:
        return _which(self.binary)

    def version(self) -> str | None:
        if not self.is_available():
            return None
        result = run_argv([self.binary, "--version"], timeout=20)
        return result.stdout.strip() or None if result.exit_code == 0 else None

    def _default_mounts(self, request: ExecutionRequest) -> list[Mount]:
        mounts = list(request.mounts)
        if not any(m.target == _WORKDIR_TARGET for m in mounts):
            mounts.insert(
                0, Mount(source=str(request.workdir), target=_WORKDIR_TARGET, read_only=False)
            )
        return mounts

    def build_argv(self, request: ExecutionRequest) -> list[str]:
        if not request.image:
            raise ValueError(f"Backend '{self.name}' requires an image.")
        argv = [self.binary, "run", "--rm"]
        if not request.network:
            argv += ["--network", "none"]
        argv += ["--workdir", _WORKDIR_TARGET]
        for mount in self._default_mounts(request):
            suffix = ":ro" if mount.read_only else ""
            argv += ["-v", f"{mount.source}:{mount.target}{suffix}"]
        if request.limits.memory:
            argv += ["--memory", request.limits.memory]
        if request.limits.cpus:
            argv += ["--cpus", request.limits.cpus]
        for key, value in request.env.items():
            argv += ["-e", f"{key}={value}"]
        argv.append(_image_ref_docker(request.image))
        argv += shlex.split(request.command)
        return argv

    def run(self, request: ExecutionRequest) -> ShellResult:
        if not self.is_available():
            return ShellResult(
                command=request.command,
                stdout="",
                stderr=f"Execution backend '{self.name}' is not installed; unavailable.",
                exit_code=127,
            )
        return run_argv(
            self.build_argv(request),
            timeout=request.limits.timeout,
            label=request.command,
        )


class DockerBackend(_OciBackend):
    name = "docker"
    binary = "docker"


class PodmanBackend(_OciBackend):
    name = "podman"
    binary = "podman"


class ApptainerBackend:
    """Rootless, daemonless backend for HPC (Apptainer/Singularity)."""

    name = "apptainer"
    binary = "apptainer"
    requires_image = True

    def is_available(self) -> bool:
        return _which(self.binary)

    def version(self) -> str | None:
        if not self.is_available():
            return None
        result = run_argv([self.binary, "--version"], timeout=20)
        return result.stdout.strip() or None if result.exit_code == 0 else None

    def build_argv(self, request: ExecutionRequest) -> list[str]:
        if not request.image:
            raise ValueError("Backend 'apptainer' requires an image.")
        argv = [self.binary, "exec"]
        # Apptainer shares the host network by default; isolate unless requested.
        if not request.network:
            argv += ["--net", "--network", "none"]
        argv += ["--pwd", _WORKDIR_TARGET]
        bound_work = any(m.target == _WORKDIR_TARGET for m in request.mounts)
        if not bound_work:
            argv += ["--bind", f"{request.workdir}:{_WORKDIR_TARGET}"]
        for mount in request.mounts:
            suffix = ":ro" if mount.read_only else ""
            argv += ["--bind", f"{mount.source}:{mount.target}{suffix}"]
        if request.limits.memory:
            argv += ["--memory", request.limits.memory]
        if request.limits.cpus:
            argv += ["--cpus", request.limits.cpus]
        for key, value in request.env.items():
            argv += ["--env", f"{key}={value}"]
        argv.append(_image_ref_apptainer(request.image))
        argv += shlex.split(request.command)
        return argv

    def run(self, request: ExecutionRequest) -> ShellResult:
        if not self.is_available():
            return ShellResult(
                command=request.command,
                stdout="",
                stderr="Execution backend 'apptainer' is not installed; unavailable.",
                exit_code=127,
            )
        return run_argv(
            self.build_argv(request),
            timeout=request.limits.timeout,
            label=request.command,
        )
