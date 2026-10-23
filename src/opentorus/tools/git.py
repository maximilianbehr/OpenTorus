"""Git inspection helpers (read-only).

Best-effort wrappers around ``git`` that degrade gracefully when the directory is
not a git repository or git is unavailable.

``git_diff`` shows what changed since ``HEAD`` -- staged, unstaged *and* new
untracked (non-ignored) files -- because a plain ``git diff`` hides exactly the
files an agent most often creates. It merges ``git status --porcelain=v2 -z``
with ``git diff HEAD --numstat``, handles a repository with no commit yet, and
pages its output with an explicit "more" marker instead of truncating silently.

Git can run code from the repository it inspects: an fsmonitor hook, an
external diff driver, a textconv filter. Every invocation here disables those
(``core.fsmonitor=false``, ``diff.external=``, ``--no-ext-diff``,
``--no-textconv``, ``core.hooksPath=/dev/null``) and takes no optional locks.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

DEFAULT_DIFF_CHARS = 20_000
# Untracked files are shown in full only up to this size each.
_UNTRACKED_PREVIEW_BYTES = 8_000

_SAFE_CONFIG = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "diff.external=",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.pager=cat",
    "-c",
    "color.ui=false",
)


class GitResult(BaseModel):
    is_repo: bool
    output: str
    truncated: bool = False
    next_offset: int | None = None


_STATE_DIR = ".opentorus"


def _git_env() -> dict[str, str]:
    from opentorus.tools.childenv import scrubbed_env

    env = scrubbed_env()
    for name in ("GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_DIFF_OPTS", "GIT_CONFIG_PARAMETERS"):
        env.pop(name, None)
    env.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "LC_ALL": "C",
        }
    )
    return env


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *_SAFE_CONFIG, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            env=_git_env(),
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_repo(cwd: Path) -> bool:
    proc = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return bool(proc and proc.returncode == 0 and proc.stdout.strip() == "true")


def _has_head(cwd: Path) -> bool:
    proc = _run_git(["rev-parse", "--verify", "--quiet", "HEAD"], cwd)
    return bool(proc and proc.returncode == 0)


def git_status(cwd: Path) -> GitResult:
    if not _is_repo(cwd):
        return GitResult(is_repo=False, output="Not a git repository.")
    proc = _run_git(["status", "--short", "--branch"], cwd)
    output = proc.stdout if proc else ""
    return GitResult(is_repo=True, output=output.rstrip() or "Working tree clean.")


@dataclass
class _Entry:
    path: str
    state: str  # human label: modified, added, deleted, renamed, untracked, conflict
    orig: str | None = None
    added: str = "?"
    removed: str = "?"


_XY_LABEL = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied"}


def _label(xy: str) -> str:
    for code in (xy[0], xy[1]):
        if code in _XY_LABEL:
            return _XY_LABEL[code]
    return "changed"


def _parse_status(raw: str) -> list[_Entry]:
    """Parse ``git status --porcelain=v2 -z`` output."""
    entries: list[_Entry] = []
    fields = raw.split("\0")
    i = 0
    while i < len(fields):
        rec = fields[i]
        i += 1
        if not rec:
            continue
        kind = rec[0]
        if kind == "1":
            parts = rec.split(" ", 8)
            if len(parts) == 9:
                entries.append(_Entry(path=parts[8], state=_label(parts[1])))
        elif kind == "2":
            parts = rec.split(" ", 9)
            orig = fields[i] if i < len(fields) else None
            i += 1
            if len(parts) == 10:
                entries.append(_Entry(path=parts[9], state=_label(parts[1]), orig=orig))
        elif kind == "u":
            parts = rec.split(" ", 10)
            if len(parts) == 11:
                entries.append(_Entry(path=parts[10], state="conflict"))
        elif kind == "?":
            entries.append(_Entry(path=rec[2:], state="untracked"))
        # "!" (ignored) and "#" (headers) are not shown.
    return entries


def _numstat(raw: str) -> dict[str, tuple[str, str]]:
    """Parse ``git diff --numstat -z`` into ``{path: (added, removed)}``."""
    out: dict[str, tuple[str, str]] = {}
    fields = raw.split("\0")
    i = 0
    while i < len(fields):
        rec = fields[i]
        i += 1
        if not rec:
            continue
        parts = rec.split("\t")
        if len(parts) < 3:
            continue
        added, removed, path = parts[0], parts[1], parts[2]
        if path == "":  # rename: the next two fields are old and new path
            path = fields[i + 1] if i + 1 < len(fields) else ""
            i += 2
        out[path] = ("bin" if added == "-" else added, "bin" if removed == "-" else removed)
    return out


def _untracked_patch(cwd: Path, rel: str) -> str:
    target = cwd / rel
    try:
        if target.is_symlink() or not target.is_file():
            return f"new file {rel} (not a regular file; not shown)\n"
        size = target.stat().st_size
        with open(target, "rb") as fh:
            head = fh.read(_UNTRACKED_PREVIEW_BYTES)
    except OSError as exc:
        return f"new file {rel} (unreadable: {exc})\n"
    if b"\0" in head:
        return f"new file {rel} (binary, {size} bytes)\n"
    text = head.decode("utf-8", errors="replace")
    lines = text.splitlines()
    body = "".join(f"+{line}\n" for line in lines)
    more = f"… ({size - len(head)} more bytes of {rel} not shown)\n" if size > len(head) else ""
    return (
        f"diff --git a/{rel} b/{rel}\nnew file (untracked)\n--- /dev/null\n+++ b/{rel}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{body}{more}"
    )


def _count_lines(cwd: Path, rel: str) -> tuple[str, str]:
    try:
        with open(cwd / rel, "rb") as fh:
            data = fh.read(4 * 1024 * 1024)
    except OSError:
        return ("?", "0")
    if b"\0" in data[:8000]:
        return ("bin", "0")
    return (str(data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)), "0")


def _page(text: str, offset: int, max_chars: int) -> tuple[str, bool, int | None]:
    offset = max(0, offset)
    window = text[offset : offset + max_chars]
    end = offset + len(window)
    if end < len(text):
        remaining = len(text) - end
        marker = (
            f"\n[… more: {remaining} chars not shown. "
            f"Call git_diff with offset={end} to continue …]"
        )
        return window + marker, True, end
    return window, False, None


def git_diff(
    cwd: Path,
    path: str | None = None,
    *,
    offset: int = 0,
    max_chars: int = DEFAULT_DIFF_CHARS,
) -> GitResult:
    """Everything that differs from ``HEAD``: staged, unstaged and untracked files."""
    if not _is_repo(cwd):
        return GitResult(is_repo=False, output="Not a git repository.")
    # OpenTorus' own state under .opentorus/ is not the agent's work and would crowd the
    # page; it is left out unless asked for by path, and its count is reported instead.
    spec = ["--", path] if path else ["--", ".", f":(exclude){_STATE_DIR}"]
    status = _run_git(["status", "--porcelain=v2", "-z", "--untracked-files=all", *spec], cwd)
    entries = _parse_status(status.stdout if status and status.returncode == 0 else "")
    hidden = 0
    if not path:
        state = _run_git(
            ["status", "--porcelain=v2", "-z", "--untracked-files=all", "--", _STATE_DIR], cwd
        )
        hidden = len(_parse_status(state.stdout if state and state.returncode == 0 else ""))
    head = _has_head(cwd)
    diff_flags = ["--no-ext-diff", "--no-textconv", "--no-color"]

    patches: list[str] = []
    counts: dict[str, tuple[str, str]] = {}
    if head:
        num = _run_git(["diff", "HEAD", "--numstat", "-z", *diff_flags, *spec], cwd)
        counts.update(_numstat(num.stdout if num else ""))
        patch = _run_git(["diff", "HEAD", *diff_flags, *spec], cwd)
        if patch and patch.stdout:
            patches.append(patch.stdout)
    else:
        # No commit yet: staged content is "new" against nothing, plus unstaged edits.
        for extra in (["--cached"], []):
            num = _run_git(["diff", *extra, "--numstat", "-z", *diff_flags, *spec], cwd)
            for key, (a, r) in _numstat(num.stdout if num else "").items():
                if key in counts and counts[key][0].isdigit() and a.isdigit():
                    a = str(int(counts[key][0]) + int(a))
                    r = str(int(counts[key][1]) + int(r)) if r.isdigit() else r
                counts[key] = (a, r)
            patch = _run_git(["diff", *extra, *diff_flags, *spec], cwd)
            if patch and patch.stdout:
                patches.append(patch.stdout)

    for entry in entries:
        if entry.state == "untracked":
            entry.added, entry.removed = _count_lines(cwd, entry.path)
            patches.append(_untracked_patch(cwd, entry.path))
        elif entry.path in counts:
            entry.added, entry.removed = counts[entry.path]

    state_note = (
        f"({hidden} changed file(s) under {_STATE_DIR}/ — OpenTorus state — not shown; "
        f"pass path='{_STATE_DIR}' to see them.)"
        if hidden
        else ""
    )
    if not entries and not patches:
        where = f" under {path}" if path else ""
        base = "HEAD" if head else "the empty repository (no commit yet)"
        message = f"No changes{where} relative to {base}."
        return GitResult(is_repo=True, output=f"{message}\n{state_note}".strip())

    header_lines = [
        f"{len(entries)} changed file(s) relative to "
        + ("HEAD" if head else "an empty repository (no commit yet)")
        + ":"
    ]
    for entry in entries:
        name = f"{entry.orig} -> {entry.path}" if entry.orig else entry.path
        header_lines.append(f"  {entry.state:<9} {name}  (+{entry.added} -{entry.removed})")
    if state_note:
        header_lines.append(state_note)
    text = "\n".join(header_lines) + "\n\n" + "".join(patches).rstrip()
    page, truncated, next_offset = _page(text, offset, max_chars)
    return GitResult(is_repo=True, output=page, truncated=truncated, next_offset=next_offset)
