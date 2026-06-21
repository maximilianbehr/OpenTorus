"""Lightweight checkpoints for safe iteration.

A checkpoint records a recoverable point before risky edits. In a git repo it
captures the branch, commit, and dirty state (and can optionally create a branch
when the user asks). Outside git it records a file manifest. Checkpoints never
auto-commit; they only record state.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl

_MANIFEST_LIMIT = 2000


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Checkpoint(BaseModel):
    id: str
    label: str
    kind: Literal["git", "manifest"]
    git_branch: str | None = None
    git_commit: str | None = None
    git_dirty: bool | None = None
    created_branch: str | None = None
    manifest: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


def checkpoints_dir(ot_dir: Path) -> Path:
    return ot_dir / "checkpoints"


def _index_path(ot_dir: Path) -> Path:
    return checkpoints_dir(ot_dir) / "index.jsonl"


def list_checkpoints(ot_dir: Path) -> list[Checkpoint]:
    return read_jsonl(_index_path(ot_dir), Checkpoint)


def get_checkpoint(ot_dir: Path, checkpoint_id: str) -> Checkpoint | None:
    target = checkpoint_id.strip().upper()
    for cp in list_checkpoints(ot_dir):
        if cp.id == target:
            return cp
    return None


class RestoreResult(BaseModel):
    """What a restore did (or would do): a git checkout, or a manifest diff."""

    checkpoint_id: str
    kind: Literal["git", "manifest"]
    applied: bool
    message: str
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


def restore_checkpoint(
    root: Path, ot_dir: Path, checkpoint_id: str, *, force: bool = False
) -> RestoreResult:
    """Restore a recorded checkpoint.

    For a ``git`` checkpoint, check out the recorded commit (refusing on a dirty
    tree unless ``force``). For a ``manifest`` checkpoint there is no stored content
    to roll back to, so report the difference between the recorded file set and the
    current one (added/removed) rather than silently doing nothing.
    """
    cp = get_checkpoint(ot_dir, checkpoint_id)
    if cp is None:
        raise OpenTorusError(f"No checkpoint with id '{checkpoint_id}'.")

    if cp.kind == "git":
        if not _is_repo(root):
            raise OpenTorusError("Checkpoint is git-based but this is no longer a git repository.")
        if not cp.git_commit:
            raise OpenTorusError(f"{cp.id} has no recorded commit to restore.")
        _branch, _commit, dirty = _git_state(root)
        if dirty and not force:
            raise OpenTorusError(
                "Working tree has uncommitted changes; commit/stash them or pass --force "
                "to discard and check out the checkpoint commit."
            )
        ref = cp.git_commit
        proc = _git(["checkout", *(["--force"] if force else []), ref], root)
        if proc is None or proc.returncode != 0:
            detail = (proc.stderr.strip() if proc else "git unavailable") or "unknown error"
            raise OpenTorusError(f"Could not check out {ref[:8]}: {detail}")
        return RestoreResult(
            checkpoint_id=cp.id,
            kind="git",
            applied=True,
            message=f"Checked out checkpoint commit {ref[:8]} (was {cp.git_branch}).",
        )

    # Manifest checkpoint: no stored bytes, so report the diff for the user to act on.
    recorded = set(cp.manifest)
    current = set(_file_manifest(root))
    added = sorted(current - recorded)
    removed = sorted(recorded - current)
    return RestoreResult(
        checkpoint_id=cp.id,
        kind="manifest",
        applied=False,
        message=(
            "Manifest checkpoints record a file list, not contents, so they cannot be "
            f"rolled back automatically. Since {cp.id}: {len(added)} added, {len(removed)} "
            "removed file(s)."
        ),
        added=added,
        removed=removed,
    )


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_repo(root: Path) -> bool:
    proc = _git(["rev-parse", "--is-inside-work-tree"], root)
    return bool(proc and proc.returncode == 0 and proc.stdout.strip() == "true")


def _git_state(root: Path) -> tuple[str | None, str | None, bool | None]:
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    commit = _git(["rev-parse", "HEAD"], root)
    status = _git(["status", "--porcelain"], root)
    return (
        branch.stdout.strip() if branch and branch.returncode == 0 else None,
        commit.stdout.strip() if commit and commit.returncode == 0 else None,
        bool(status.stdout.strip()) if status and status.returncode == 0 else None,
    )


def _file_manifest(root: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        parts = rel.parts
        if parts and parts[0] in {".opentorus", ".git"}:
            continue
        files.append(str(rel))
        if len(files) >= _MANIFEST_LIMIT:
            break
    return files


def create_checkpoint(
    root: Path,
    ot_dir: Path,
    label: str,
    create_branch: str | None = None,
) -> Checkpoint:
    """Record a checkpoint of the current state (git metadata or file manifest)."""
    existing = list_checkpoints(ot_dir)
    checkpoint_id = next_sequential_id("CHECKPOINT", len(existing))

    if _is_repo(root):
        branch, commit, dirty = _git_state(root)
        created_branch: str | None = None
        if create_branch:
            proc = _git(["checkout", "-b", create_branch], root)
            if proc is None or proc.returncode != 0:
                detail = (proc.stderr.strip() if proc else "git unavailable") or "unknown error"
                raise OpenTorusError(f"Could not create branch '{create_branch}': {detail}")
            created_branch = create_branch
            branch = create_branch
        checkpoint = Checkpoint(
            id=checkpoint_id,
            label=label,
            kind="git",
            git_branch=branch,
            git_commit=commit,
            git_dirty=dirty,
            created_branch=created_branch,
        )
    else:
        checkpoint = Checkpoint(
            id=checkpoint_id,
            label=label,
            kind="manifest",
            manifest=_file_manifest(root),
        )

    append_jsonl(_index_path(ot_dir), checkpoint)
    return checkpoint
