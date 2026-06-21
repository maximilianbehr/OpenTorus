"""Guarded shell execution.

``run_shell`` is a thin, side-effect-light wrapper around ``subprocess.run``
(no ``shell=True``; the command is tokenized with ``shlex``). ``execute_command``
adds the policy layer: it evaluates permission, optionally asks for confirmation,
runs the command, and records an action-log entry.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

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


def run_argv(
    argv: list[str],
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    *,
    label: str | None = None,
    env: dict[str, str] | None = None,
) -> ShellResult:
    """Execute a pre-tokenized argv without a shell, capturing output.

    ``label`` is the human-readable command string recorded on the result (useful
    when the real argv is a container invocation wrapping a logical command).
    """
    command = label or " ".join(argv)
    if not argv:
        return ShellResult(command=command, stdout="", stderr="empty command", exit_code=1)
    run_env = {**os.environ, **env} if env else None
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            # Tools such as pdflatex emit non-UTF-8 bytes (e.g. Latin-1 in error
            # messages); decode leniently so reading their output never raises a
            # UnicodeDecodeError that would mask the real (non-zero) exit status.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=run_env,
        )
    except FileNotFoundError as exc:
        return ShellResult(command=command, stdout="", stderr=str(exc), exit_code=127)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        stdout = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        stderr = err.decode("utf-8", "replace") if isinstance(err, bytes) else err
        return ShellResult(
            command=command,
            stdout=stdout,
            stderr=stderr or f"Timed out after {timeout}s",
            exit_code=124,
            timed_out=True,
        )
    return ShellResult(
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        timed_out=False,
    )


def run_shell(
    command: str, cwd: Path | str | None = None, timeout: int = DEFAULT_TIMEOUT
) -> ShellResult:
    """Execute ``command`` without a shell, capturing output and exit code."""
    return run_argv(shlex.split(command), cwd=cwd, timeout=timeout, label=command)


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
    timeout: int = DEFAULT_TIMEOUT,
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

    result = run_shell(command, cwd=workspace_dir.parent, timeout=timeout)
    _log(result.exit_code == 0, result)
    return decision, result
