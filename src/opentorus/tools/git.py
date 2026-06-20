"""Git inspection helpers (read-only).

Best-effort wrappers around ``git`` that degrade gracefully when the directory is
not a git repository or git is unavailable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel


class GitResult(BaseModel):
    is_repo: bool
    output: str


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_repo(cwd: Path) -> bool:
    proc = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return bool(proc and proc.returncode == 0 and proc.stdout.strip() == "true")


def git_status(cwd: Path) -> GitResult:
    if not _is_repo(cwd):
        return GitResult(is_repo=False, output="Not a git repository.")
    proc = _run_git(["status", "--short", "--branch"], cwd)
    output = proc.stdout if proc else ""
    return GitResult(is_repo=True, output=output.rstrip() or "Working tree clean.")


def git_diff(cwd: Path, path: str | None = None) -> GitResult:
    if not _is_repo(cwd):
        return GitResult(is_repo=False, output="Not a git repository.")
    args = ["diff"]
    if path:
        args += ["--", path]
    proc = _run_git(args, cwd)
    output = proc.stdout if proc else ""
    return GitResult(is_repo=True, output=output.rstrip() or "No unstaged changes.")
