"""Guarded shell execution.

``run_shell`` is a thin, side-effect-light wrapper around ``subprocess.run``
(no ``shell=True``; the command is tokenized with ``shlex``). ``execute_command``
adds the policy layer: it evaluates permission, optionally asks for confirmation,
runs the command, and records an action-log entry.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from opentorus.actions import log_action
from opentorus.config import OperatingStyle, PermissionMode
from opentorus.permissions.policy import PermissionDecision, evaluate_command

DEFAULT_TIMEOUT = 30

# A confirmation callback receives the decision and returns True to allow.
ConfirmCallback = Callable[[PermissionDecision], bool]


class ShellResult(BaseModel):
    command: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


EnvPolicy = Literal["scrubbed", "clean"]

# Grace between SIGTERM and SIGKILL when a process group is torn down.
_TERM_GRACE = 2.0
# How long to wait for the output pipes to drain once the process group is gone.
# A descendant that detached itself (setsid/nohup) keeps the pipe open; we do not
# wait for it forever.
_DRAIN_TIMEOUT = 2.0


def _child_env(
    env: Mapping[str, str] | None, policy: EnvPolicy, allowlist: Iterable[str]
) -> dict[str, str]:
    from opentorus.tools.childenv import clean_env, scrubbed_env

    if policy == "clean":
        return clean_env(env, allowlist=allowlist)
    return scrubbed_env(env)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def terminate_process_group(proc: subprocess.Popen, *, grace: float = _TERM_GRACE) -> None:
    """SIGTERM the process group ``proc`` leads, then SIGKILL whatever is left.

    POSIX only. Every child OpenTorus starts is the leader of its own session
    (``start_new_session=True``), so its pgid is its pid and the group holds every
    descendant that did not detach on purpose. Reaps ``proc`` before returning.
    """
    if os.name == "nt":  # pragma: no cover - POSIX CI
        proc.kill()
        proc.wait()
        return
    pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.monotonic() + grace
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # The leader is reaped (or still stuck); a pgid is never handed out again while a
    # group with that id exists, so polling it only ever sees our own leftovers.
    while time.monotonic() < deadline and _group_alive(pgid):
        time.sleep(0.02)
    if _group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    proc.wait()


def _exited_unreaped(pid: int) -> bool:
    """True once ``pid`` has exited, *without* reaping it.

    Leaving the zombie in place keeps its pid (and so the process-group id) from
    being reused while the leftover descendants are killed.
    """
    try:
        info = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return True
    return info is not None


def _reader(stream, sink: list[bytes]) -> None:  # noqa: ANN001
    try:
        for chunk in iter(lambda: stream.read1(65536), b""):
            sink.append(chunk)
    except (OSError, ValueError):
        pass


def _decode(chunks: list[bytes]) -> str:
    # Tools such as pdflatex emit non-UTF-8 bytes (e.g. Latin-1 in error messages);
    # decode leniently so reading their output never raises a UnicodeDecodeError
    # that would mask the real (non-zero) exit status.
    return b"".join(chunks).decode("utf-8", errors="replace")


def _run_posix(
    argv: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    timeout: float,
    preexec_fn: Callable[[], None] | None,
) -> tuple[str, str, int, bool]:
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
        preexec_fn=preexec_fn,
    )
    out: list[bytes] = []
    err: list[bytes] = []
    threads = [
        threading.Thread(target=_reader, args=(proc.stdout, out), daemon=True),
        threading.Thread(target=_reader, args=(proc.stderr, err), daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        deadline = time.monotonic() + timeout
        delay = 0.005
        while not _exited_unreaped(proc.pid):
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(delay)
            delay = min(delay * 2, 0.05)
    except BaseException:
        # Cancel (Ctrl-C, a cancelled turn): the whole group goes, not just the leader.
        terminate_process_group(proc)
        raise
    # On timeout this ends the command; on a normal exit it ends descendants the
    # command left running in the background. Either way nothing outlives it.
    terminate_process_group(proc, grace=_TERM_GRACE if timed_out else 0.5)
    returncode = proc.returncode if proc.returncode is not None else proc.wait()
    for thread in threads:
        thread.join(_DRAIN_TIMEOUT)
    for stream in (proc.stdout, proc.stderr):
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass
    return _decode(out), _decode(err), returncode, timed_out


def _run_windows(  # pragma: no cover - POSIX CI
    argv: list[str] | str, *, cwd: str | None, env: dict[str, str], timeout: float
) -> tuple[str, str, int, bool]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        o = exc.stdout or ""
        e = exc.stderr or ""
        so = o.decode("utf-8", "replace") if isinstance(o, bytes) else o
        se = e.decode("utf-8", "replace") if isinstance(e, bytes) else e
        return so, se, 124, True
    return completed.stdout, completed.stderr, completed.returncode, False


def run_argv(
    argv: list[str] | str,
    cwd: Path | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    label: str | None = None,
    env: dict[str, str] | None = None,
    env_policy: EnvPolicy = "scrubbed",
    env_allowlist: Iterable[str] = (),
    preexec_fn: Callable[[], None] | None = None,
) -> ShellResult:
    """Execute a pre-tokenized argv without a shell, capturing output.

    ``label`` is the human-readable command string recorded on the result (useful
    when the real argv is a container invocation wrapping a logical command).
    On Windows ``argv`` may be the raw command string: it is handed to
    ``CreateProcess`` verbatim (still no shell), because POSIX tokenization
    corrupts ``C:\\``-style paths.

    The child never sees credentials: ``env_policy="scrubbed"`` passes the parent
    environment minus every credential-looking name, ``"clean"`` passes only the
    allowlist (see :mod:`opentorus.tools.childenv`). On POSIX the child leads its
    own process group, and a timeout, a cancel, or the command's own exit kills the
    whole group (SIGTERM, then SIGKILL), so no grandchild keeps running.
    """
    command = label or (argv if isinstance(argv, str) else " ".join(argv))
    if not argv:
        return ShellResult(command=command, stdout="", stderr="empty command", exit_code=1)
    run_env = _child_env(env, env_policy, env_allowlist)
    cwd_str = str(cwd) if cwd else None
    try:
        if os.name == "nt":  # pragma: no cover - POSIX CI
            stdout, stderr, code, timed_out = _run_windows(
                argv, cwd=cwd_str, env=run_env, timeout=timeout
            )
        else:
            stdout, stderr, code, timed_out = _run_posix(
                list(argv) if not isinstance(argv, str) else shlex.split(argv),
                cwd=cwd_str,
                env=run_env,
                timeout=timeout,
                preexec_fn=preexec_fn,
            )
    except FileNotFoundError as exc:
        return ShellResult(command=command, stdout="", stderr=str(exc), exit_code=127)
    except PermissionError as exc:
        return ShellResult(command=command, stdout="", stderr=str(exc), exit_code=126)
    if timed_out:
        return ShellResult(
            command=command,
            stdout=stdout,
            stderr=stderr
            or (
                f"Timed out after {timeout:g}s — this is the caller-supplied limit, "
                "not a property of the command. Anything the command printed before "
                "the cut is above; re-run with a larger timeout if the work "
                "legitimately needs one, or make the command do less."
            ),
            exit_code=124,
            timed_out=True,
        )
    return ShellResult(
        command=command,
        stdout=stdout,
        stderr=stderr,
        exit_code=code,
        timed_out=False,
    )


def run_shell(
    command: str,
    cwd: Path | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    env_policy: EnvPolicy = "scrubbed",
    env_allowlist: Iterable[str] = (),
) -> ShellResult:
    """Execute ``command`` without a shell, capturing output and exit code.

    POSIX hosts tokenize with ``shlex``; Windows passes the string through to
    ``CreateProcess`` (shlex's POSIX rules would eat the backslashes in
    ``C:\\...\\python.exe`` and nothing would be found to run).
    """
    argv: list[str] | str = command if os.name == "nt" else shlex.split(command)
    return run_argv(
        argv,
        cwd=cwd,
        timeout=timeout,
        label=command,
        env_policy=env_policy,
        env_allowlist=env_allowlist,
    )


def _summarize(text: str, limit: int = 500) -> str | None:
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def execute_command(
    workspace_dir: Path,
    command: str,
    mode: PermissionMode,
    *,
    style: OperatingStyle = "normal",
    review: bool = False,
    confirm: ConfirmCallback | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    env_allowlist: Iterable[str] = (),
) -> tuple[PermissionDecision, ShellResult | None]:
    """Permission-check, optionally confirm, run, and log a shell command.

    Returns the decision and the result (``None`` if the command did not run).
    """
    decision = evaluate_command(command, mode, style=style, review=review)

    def _log(ok: bool, result: ShellResult | None) -> None:
        log_action(
            workspace_dir,
            "run_shell",
            ok=ok,
            args={"command": command},
            permission_decision=decision.model_dump(),
            stdout_summary=_summarize(result.stdout) if result else None,
            stderr_summary=_summarize(result.stderr) if result else None,
        )

    if not decision.allowed:
        _log(False, None)
        return decision, None

    if decision.requires_confirmation:
        approved = confirm(decision) if confirm is not None else False
        if not approved:
            _log(False, None)
            return decision, None

    result = run_shell(
        command,
        cwd=workspace_dir.parent,
        timeout=timeout,
        env_policy="clean",
        env_allowlist=env_allowlist,
    )
    _log(result.exit_code == 0, result)
    return decision, result
