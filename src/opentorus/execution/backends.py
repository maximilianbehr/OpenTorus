"""Concrete execution backends: local host, Docker, Podman, Apptainer.

Container backends build an explicit argv that wraps the logical command, apply
least-privilege defaults (no network unless requested, read-only workspace mount,
optional cpu/memory limits), and run it via the shared ``run_argv`` helper so the
result shape matches the rest of OpenTorus. The argv assembly is pure and tested
without invoking any real container.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path

from opentorus.execution.base import WORKDIR_TARGET as _WORKDIR_TARGET
from opentorus.execution.base import ExecutionRequest, Mount
from opentorus.tools.shell import ShellResult, run_argv

# Labels stamped on every container OpenTorus starts, so a container whose owner
# died without running its cleanup can still be identified and reaped later.
OWNER_PID_LABEL = "org.opentorus.owner-pid"
OWNER_HOST_LABEL = "org.opentorus.owner-host"


def _which(binary: str) -> bool:
    return shutil.which(binary) is not None


def _host_id() -> str:
    """Identify this host, so PID labels are only trusted for containers we own.

    A remote container daemon runs other machines' PIDs; reaping by PID liveness
    there would kill live work.
    """
    import platform

    return platform.node() or "unknown"


def _process_alive(pid: int) -> bool:
    """True if ``pid`` names a live process on this host.

    POSIX only. On Windows ``os.kill(pid, 0)`` does **not** probe — CPython maps
    every signal other than CTRL_C_EVENT/CTRL_BREAK_EVENT to ``TerminateProcess``,
    so the probe would kill the very process it asks about, and this answer decides
    whether a container gets reaped. Reporting "alive" there costs an unreaped
    container after a hard kill; the alternative costs a running OpenTorus.
    """
    if os.name == "nt":  # pragma: no cover - POSIX CI
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, owned by someone else.
        return True
    except OSError:
        return True
    return True


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
        # Windows: hand the command string to CreateProcess verbatim — POSIX
        # tokenization corrupts C:\-style paths (see run_shell).
        argv: list[str] | str = request.command if os.name == "nt" else self.build_argv(request)
        return run_argv(
            argv,
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
                0,
                Mount(
                    # as_posix: container CLIs accept C:/-style sources on
                    # Windows, and the argv is recorded in manifests.
                    source=Path(request.workdir).as_posix(),
                    target=_WORKDIR_TARGET,
                    read_only=False,
                ),
            )
        return mounts

    def build_argv(self, request: ExecutionRequest, *, name: str | None = None) -> list[str]:
        if not request.image:
            raise ValueError(f"Backend '{self.name}' requires an image.")
        argv = [self.binary, "run", "--rm"]
        if name:
            argv += ["--name", name]
            # Stamp the owner so a container that outlived its process can be
            # recognised as an orphan later, from any OpenTorus run on this host.
            argv += ["--label", f"{OWNER_PID_LABEL}={os.getpid()}"]
            argv += ["--label", f"{OWNER_HOST_LABEL}={_host_id()}"]
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
        # A timeout (or a Ctrl-C) kills the ``docker run`` *client*, not the container:
        # after a stress test twelve orphaned experiment containers were still burning
        # CPU hours after the runs that started them had ended. Naming the container
        # lets the backend stop it whenever the client did not exit cleanly.
        #
        # That cleanup runs in ``finally``, which a SIGKILL/SIGALRM of the OpenTorus
        # process itself skips — a later stress run found an experiment container
        # still going 26 minutes after its owner was killed. The owner labels let
        # any subsequent run reap it, so recovery no longer depends on the dying
        # process getting a chance to clean up after itself.
        self.reap_orphans()
        name = f"opentorus-{uuid.uuid4().hex[:12]}"
        clean_exit = False
        try:
            result = run_argv(
                self.build_argv(request, name=name),
                timeout=request.limits.timeout,
                label=request.command,
            )
            clean_exit = not result.timed_out
            return result
        finally:
            if not clean_exit:
                self._kill(name)

    def _kill(self, name: str) -> None:
        """Best-effort stop of a named container whose client did not exit cleanly."""
        try:
            subprocess.run(
                [self.binary, "kill", name],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def orphan_containers(self) -> list[str]:
        """Names of running OpenTorus containers whose owning process is gone.

        Only containers labelled with *this* host are considered: a remote daemon
        runs another machine's PIDs, where local liveness says nothing.
        """
        fmt = (
            "{{.Names}}\t"
            f'{{{{.Label "{OWNER_PID_LABEL}"}}}}\t'
            f'{{{{.Label "{OWNER_HOST_LABEL}"}}}}'
        )
        result = run_argv(
            [self.binary, "ps", "--filter", f"label={OWNER_PID_LABEL}", "--format", fmt],
            timeout=30,
        )
        if result.exit_code != 0:
            return []
        here = _host_id()
        orphans: list[str] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            container, raw_pid, host = (part.strip() for part in parts[:3])
            if not container or host != here:
                continue
            try:
                pid = int(raw_pid)
            except ValueError:
                continue
            if pid != os.getpid() and not _process_alive(pid):
                orphans.append(container)
        return orphans

    def reap_orphans(self) -> list[str]:
        """Kill containers left behind by an OpenTorus process that no longer exists.

        Best effort and never fatal: a failed reap must not stop the run that
        noticed the orphan.
        """
        killed: list[str] = []
        try:
            orphans = self.orphan_containers()
        except (OSError, subprocess.SubprocessError):
            return killed
        for container in orphans:
            self._kill(container)
            killed.append(container)
        return killed


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
            # as_posix: bind sources are recorded in manifests and must not
            # vary with the host's path separator.
            argv += ["--bind", f"{Path(request.workdir).as_posix()}:{_WORKDIR_TARGET}"]
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
