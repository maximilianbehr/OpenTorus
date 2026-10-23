"""Concrete execution backends: local host, Docker, Podman, Apptainer.

Container backends build an explicit argv that wraps the logical command, apply
least-privilege defaults, and run it via the shared ``run_argv`` helper so the
result shape matches the rest of OpenTorus. The argv assembly is pure and tested
without invoking any real container.

Defaults, stated exactly:

* no network unless the request asks for it;
* the request's working directory is bound **read-write** at ``/work`` -- it is the
  run's own directory (an experiment or figure dir) and outputs are written there.
  When that directory is a workspace root, its ``.opentorus/`` artifact store is
  bound again **read-only** on top, so a run can never rewrite claims, evidence or
  logs. A caller that wants the whole workspace read-only passes
  :func:`opentorus.execution.base.sandboxed_mounts` (read-only ``/work`` plus one
  writable ``results/``);
* Apptainer runs with ``--containall --cleanenv``: no host environment, no host
  ``$HOME`` (so no ``~/.ssh``), private ``/tmp``, PID and IPC namespaces;
* optional cpu/memory limits.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path

from opentorus.execution.base import WORKDIR_TARGET as _WORKDIR_TARGET
from opentorus.execution.base import ExecutionRequest, Mount
from opentorus.tools.shell import ShellResult, run_argv

_logger = logging.getLogger("opentorus")

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


def _workspace_store_guard(workdir: Path | str, mounts: list[Mount]) -> list[Mount]:
    """A read-only re-bind of ``<workdir>/.opentorus`` when the workdir is a workspace."""
    from opentorus.paths import WORKSPACE_DIRNAME

    store = Path(workdir) / WORKSPACE_DIRNAME
    target = f"{_WORKDIR_TARGET}/{WORKSPACE_DIRNAME}"
    if not store.is_dir() or any(m.target == target for m in mounts):
        return []
    return [Mount(source=store.as_posix(), target=target, read_only=True)]


def _image_ref_docker(image: str) -> str:
    return image


def _image_ref_apptainer(image: str) -> str:
    """Apptainer needs a source: a local ``.sif``/path, else a ``docker://`` ref."""
    if image.startswith(("/", "./", "../")) or image.endswith(".sif"):
        return image
    if "://" in image:
        return image
    return f"docker://{image}"


_BWRAP_OK: dict[str, bool] = {}


def bwrap_usable() -> bool:
    """Whether bubblewrap exists *and* can create a network namespace here.

    Unprivileged user namespaces are disabled on some hosts, where ``bwrap`` is
    installed but every invocation fails; probing once keeps that honest.
    """
    path = shutil.which("bwrap")
    if path is None:
        return False
    if path not in _BWRAP_OK:
        try:
            probe = subprocess.run(
                [path, "--unshare-net", "--die-with-parent", "--dev-bind", "/", "/", "true"],
                capture_output=True,
                timeout=10,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            _BWRAP_OK[path] = probe.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _BWRAP_OK[path] = False
    return _BWRAP_OK[path]


def bwrap_prefix(workdir: Path | str) -> list[str]:
    """``bwrap`` argv that removes the network and hides host sockets under /run.

    The filesystem stays as it is (``--dev-bind / /``): confinement here is about
    the network, not about files. A network namespace has only loopback, so the
    local vLLM/Ollama servers and every remote host are out of reach; ``--tmpfs
    /run`` hides filesystem sockets (docker, dbus) that a namespace does not cover.
    """
    work = os.path.abspath(str(workdir))
    argv = [shutil.which("bwrap") or "bwrap", "--unshare-net", "--die-with-parent"]
    argv += ["--dev-bind", "/", "/"]
    if not (work == "/run" or work.startswith("/run/")):
        argv += ["--tmpfs", "/run"]
    argv += ["--chdir", work, "--"]
    return argv


_MEMORY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)i?b?\s*$", re.IGNORECASE)


def parse_memory(value: str) -> int:
    """``"2g"`` / ``"512m"`` / ``"1024"`` (bytes) -> bytes."""
    match = _MEMORY_RE.match(value)
    if not match:
        raise ValueError(f"Unrecognised memory limit {value!r} (use e.g. 512m, 2g).")
    number, unit = float(match.group(1)), match.group(2).lower()
    scale = {"": 1, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30, "t": 1 << 40}[unit]
    return int(number * scale)


def _limits_preexec(memory: int | None, cpu_seconds: int | None, cpus: int | None):  # noqa: ANN202
    """A ``preexec_fn`` applying rlimits and CPU affinity in the child (POSIX)."""
    if memory is None and cpu_seconds is None and cpus is None:
        return None

    def apply() -> None:
        import resource

        if memory is not None:
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        if cpu_seconds is not None:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
        if cpus is not None and hasattr(os, "sched_setaffinity"):
            allowed = sorted(os.sched_getaffinity(0))
            os.sched_setaffinity(0, allowed[: max(1, cpus)])

    return apply


class LocalBackend:
    """Run on the host.

    The child sees only the clean, allowlisted environment (never credentials) and
    leads its own process group, so a timeout or cancel ends every descendant.

    Confinement (``execution.local_confinement``):

    * ``auto`` (default): a request with ``network=False`` runs inside ``bwrap
      --unshare-net`` when bubblewrap works on this host; otherwise it runs
      unconfined (the result's stderr says so).
    * ``require``: such a request is **refused** when it cannot be confined.
    * ``off``: never wrapped.

    Resource limits apply in every mode on POSIX: ``memory`` -> ``RLIMIT_AS``,
    ``cpus`` -> CPU affinity to that many cores plus ``RLIMIT_CPU`` of
    ``timeout x cpus`` seconds.
    """

    name = "local"
    requires_image = False

    def __init__(
        self,
        *,
        env_allowlist: list[str] | tuple[str, ...] = (),
        confinement: str = "auto",
    ) -> None:
        self.env_allowlist = tuple(env_allowlist)
        if confinement not in ("off", "auto", "require"):
            raise ValueError(f"Unknown local confinement {confinement!r}.")
        self.confinement = confinement
        # How the last run was confined ("bwrap" / "none"), for provenance.
        self.last_confinement: str | None = None

    def is_available(self) -> bool:
        return True

    def version(self) -> str | None:
        return "host"

    def build_argv(self, request: ExecutionRequest) -> list[str]:
        return shlex.split(request.command)

    def _refuse(self, request: ExecutionRequest, why: str) -> ShellResult:
        self.last_confinement = None
        return ShellResult(
            command=request.command,
            stdout="",
            stderr=f"Run not executed: {why}",
            exit_code=126,
        )

    def run(self, request: ExecutionRequest) -> ShellResult:
        # Windows: hand the command string to CreateProcess verbatim — POSIX
        # tokenization corrupts C:\-style paths (see run_shell).
        if os.name == "nt":  # pragma: no cover - POSIX CI
            if self.confinement == "require" and not request.network:
                return self._refuse(request, "local confinement is not available on Windows.")
            self.last_confinement = "none"
            return run_argv(
                request.command,
                cwd=request.workdir,
                timeout=request.limits.timeout,
                label=request.command,
                env=request.env or None,
                env_policy="clean",
                env_allowlist=self.env_allowlist,
            )
        argv = self.build_argv(request)
        if not request.network and self.confinement != "off":
            if bwrap_usable():
                argv = [*bwrap_prefix(request.workdir), *argv]
                self.last_confinement = "bwrap"
            elif self.confinement == "require":
                return self._refuse(
                    request,
                    "execution.local_confinement is 'require' and the run asks for no "
                    "network, but bubblewrap (bwrap) is unavailable or cannot create a "
                    "network namespace on this host.",
                )
            else:
                self.last_confinement = "none"
                _logger.info(
                    "network=False requested but bubblewrap is unavailable; running %r "
                    "without network confinement (set execution.local_confinement=require "
                    "to refuse instead).",
                    request.command,
                )
        else:
            self.last_confinement = "none"
        try:
            memory = parse_memory(request.limits.memory) if request.limits.memory else None
            cpus = max(1, int(float(request.limits.cpus))) if request.limits.cpus else None
        except ValueError as exc:
            return self._refuse(request, str(exc))
        cpu_seconds = int(request.limits.timeout * cpus) + 1 if cpus else None
        result = run_argv(
            argv,
            cwd=request.workdir,
            timeout=request.limits.timeout,
            label=request.command,
            env=request.env or None,
            env_policy="clean",
            env_allowlist=self.env_allowlist,
            preexec_fn=_limits_preexec(memory, cpu_seconds, cpus),
        )
        return result


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
            mounts.extend(_workspace_store_guard(request.workdir, mounts))
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
        # Apptainer passes the whole host environment and binds $HOME by default --
        # on an HPC login node that is every API key in the shell and ~/.ssh.
        # --containall = --contain (no $HOME, private /tmp and /dev) + --cleanenv +
        # PID/IPC namespaces; only the binds below (and --env) reach the container.
        argv = [self.binary, "exec", "--containall", "--cleanenv"]
        # Apptainer shares the host network by default; isolate unless requested.
        if not request.network:
            argv += ["--net", "--network", "none"]
        argv += ["--pwd", _WORKDIR_TARGET]
        mounts = list(request.mounts)
        bound_work = any(m.target == _WORKDIR_TARGET for m in mounts)
        if not bound_work:
            # as_posix: bind sources are recorded in manifests and must not
            # vary with the host's path separator.
            argv += ["--bind", f"{Path(request.workdir).as_posix()}:{_WORKDIR_TARGET}"]
            mounts.extend(_workspace_store_guard(request.workdir, mounts))
        for mount in mounts:
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
