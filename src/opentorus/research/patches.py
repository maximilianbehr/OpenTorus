"""Patches as first-class artifacts.

A patch is proposed, inspected, then applied or rejected — and applied patches can
be reverted. Each patch stores a unified diff (for humans) at
``.opentorus/patches/PATCH-0001.diff``, a metadata note at ``PATCH-0001.md``, and
a structured change set (old/new file contents) at ``PATCH-0001.changes.json``
used to apply and revert deterministically. Status transitions are enforced.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl, rewrite_jsonl
from opentorus.paths import resolve_workspace_path
from opentorus.tools.filesystem import patch_preview

PatchStatus = Literal["proposed", "applied", "rejected", "reverted"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FileChange(BaseModel):
    path: str
    old_content: str
    new_content: str
    is_new: bool = False


class PatchArtifact(BaseModel):
    id: str
    task_id: str | None = None
    reason: str = ""
    files_changed: list[str] = Field(default_factory=list)
    status: PatchStatus = "proposed"
    diff_path: str
    metadata_path: str
    created_at: datetime = Field(default_factory=_utcnow)
    applied_at: datetime | None = None
    test_result: str | None = None


def patches_dir(ot_dir: Path) -> Path:
    return ot_dir / "patches"


def _index_path(ot_dir: Path) -> Path:
    return patches_dir(ot_dir) / "index.jsonl"


def _changes_path(ot_dir: Path, patch_id: str) -> Path:
    return patches_dir(ot_dir) / f"{patch_id}.changes.json"


def list_patches(ot_dir: Path) -> list[PatchArtifact]:
    return read_jsonl(_index_path(ot_dir), PatchArtifact)


def get_patch(ot_dir: Path, patch_id: str) -> PatchArtifact | None:
    for patch in list_patches(ot_dir):
        if patch.id == patch_id:
            return patch
    return None


def _save_index(ot_dir: Path, patches: list[PatchArtifact]) -> None:
    rewrite_jsonl(_index_path(ot_dir), patches)


def _load_changes(ot_dir: Path, patch_id: str) -> list[FileChange]:
    path = _changes_path(ot_dir, patch_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [FileChange.model_validate(item) for item in raw]


def read_diff(ot_dir: Path, patch: PatchArtifact) -> str:
    return (ot_dir / patch.diff_path).read_text(encoding="utf-8")


def propose_patch(
    root: Path,
    ot_dir: Path,
    edits: list[tuple[str, str]],
    reason: str,
    task_id: str | None = None,
) -> PatchArtifact:
    """Propose a patch from ``(path, new_content)`` edits.

    The current file contents become the patch's old state, so the patch can be
    applied and later reverted exactly. Nothing is written to the working tree
    here — the patch is only stored as a proposal.
    """
    if not edits:
        raise OpenTorusError("A patch must contain at least one file edit.")

    base = patches_dir(ot_dir)
    base.mkdir(parents=True, exist_ok=True)
    existing = list_patches(ot_dir)
    patch_id = next_sequential_id("PATCH", len(existing))

    changes: list[FileChange] = []
    diff_parts: list[str] = []
    for user_path, new_content in edits:
        target = resolve_workspace_path(root, user_path)
        is_new = not target.is_file()
        old_content = "" if is_new else target.read_text(encoding="utf-8")
        changes.append(
            FileChange(
                path=user_path, old_content=old_content, new_content=new_content, is_new=is_new
            )
        )
        diff_parts.append(patch_preview(old_content, new_content, user_path))

    diff_text = "".join(diff_parts)
    diff_rel = f"patches/{patch_id}.diff"
    meta_rel = f"patches/{patch_id}.md"
    (ot_dir / diff_rel).write_text(diff_text, encoding="utf-8")

    files_changed = [c.path for c in changes]
    (ot_dir / meta_rel).write_text(
        f"# {patch_id}\n\n"
        f"- Status: proposed\n"
        f"- Task: {task_id or '(none)'}\n"
        f"- Reason: {reason}\n\n"
        "## Files changed\n\n" + "\n".join(f"- {p}" for p in files_changed) + "\n",
        encoding="utf-8",
    )
    _changes_path(ot_dir, patch_id).write_text(
        json.dumps([c.model_dump() for c in changes], indent=2), encoding="utf-8"
    )

    patch = PatchArtifact(
        id=patch_id,
        task_id=task_id,
        reason=reason,
        files_changed=files_changed,
        status="proposed",
        diff_path=diff_rel,
        metadata_path=meta_rel,
    )
    append_jsonl(_index_path(ot_dir), patch)
    return patch


def record_applied_patch(
    ot_dir: Path,
    changes: list[FileChange],
    reason: str,
    task_id: str | None = None,
) -> PatchArtifact:
    """Record edits the agent already wrote to the working tree as a patch.

    Unlike :func:`propose_patch`, this does not touch the working tree (the agent
    has already written the new contents); it captures an inspectable, revertable
    artifact with status ``applied``. Git history is never touched.
    """
    changes = [c for c in changes if c.old_content != c.new_content or c.is_new]
    if not changes:
        raise OpenTorusError("No effective changes to record.")

    base = patches_dir(ot_dir)
    base.mkdir(parents=True, exist_ok=True)
    patch_id = next_sequential_id("PATCH", len(list_patches(ot_dir)))

    diff_text = "".join(patch_preview(c.old_content, c.new_content, c.path) for c in changes)
    diff_rel = f"patches/{patch_id}.diff"
    meta_rel = f"patches/{patch_id}.md"
    files_changed = [c.path for c in changes]
    (ot_dir / diff_rel).write_text(diff_text, encoding="utf-8")
    (ot_dir / meta_rel).write_text(
        f"# {patch_id}\n\n"
        f"- Status: applied\n"
        f"- Task: {task_id or '(none)'}\n"
        f"- Reason: {reason}\n\n"
        "## Files changed\n\n" + "\n".join(f"- {p}" for p in files_changed) + "\n",
        encoding="utf-8",
    )
    _changes_path(ot_dir, patch_id).write_text(
        json.dumps([c.model_dump() for c in changes], indent=2), encoding="utf-8"
    )

    patch = PatchArtifact(
        id=patch_id,
        task_id=task_id,
        reason=reason,
        files_changed=files_changed,
        status="applied",
        diff_path=diff_rel,
        metadata_path=meta_rel,
        applied_at=_utcnow(),
    )
    append_jsonl(_index_path(ot_dir), patch)
    return patch


def _require(ot_dir: Path, patch_id: str, expected: set[str]) -> tuple[list[PatchArtifact], int]:
    patches = list_patches(ot_dir)
    index = next((i for i, p in enumerate(patches) if p.id == patch_id), None)
    if index is None:
        raise OpenTorusError(f"No patch with id '{patch_id}'.")
    if patches[index].status not in expected:
        allowed = ", ".join(sorted(expected))
        raise OpenTorusError(f"{patch_id} is '{patches[index].status}'; expected one of {allowed}.")
    return patches, index


def apply_patch_artifact(root: Path, ot_dir: Path, patch_id: str) -> PatchArtifact:
    """Apply a proposed patch to the working tree and mark it applied."""
    patches, index = _require(ot_dir, patch_id, {"proposed"})
    for change in _load_changes(ot_dir, patch_id):
        target = resolve_workspace_path(root, change.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.new_content, encoding="utf-8")
    patches[index].status = "applied"
    patches[index].applied_at = _utcnow()
    _save_index(ot_dir, patches)
    return patches[index]


def reject_patch(ot_dir: Path, patch_id: str) -> PatchArtifact:
    """Reject a proposed patch without touching the working tree."""
    patches, index = _require(ot_dir, patch_id, {"proposed"})
    patches[index].status = "rejected"
    _save_index(ot_dir, patches)
    return patches[index]


def revert_patch(root: Path, ot_dir: Path, patch_id: str) -> PatchArtifact:
    """Revert an applied patch by restoring the recorded old contents."""
    patches, index = _require(ot_dir, patch_id, {"applied"})
    for change in _load_changes(ot_dir, patch_id):
        target = resolve_workspace_path(root, change.path)
        target.write_text(change.old_content, encoding="utf-8")
    patches[index].status = "reverted"
    _save_index(ot_dir, patches)
    return patches[index]
