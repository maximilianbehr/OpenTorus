"""Tests for checkpoints (Milestone 14)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opentorus.research.checkpoints import create_checkpoint, list_checkpoints
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_checkpoint_manifest_outside_git(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")

    cp = create_checkpoint(tmp_path, ot, "before edits")
    assert cp.id == "CHECKPOINT-0001"
    assert cp.kind == "manifest"
    assert "a.txt" in cp.manifest and "b.txt" in cp.manifest
    # The .opentorus tree must be excluded from the manifest.
    assert not any(f.startswith(".opentorus") for f in cp.manifest)

    second = create_checkpoint(tmp_path, ot, "later")
    assert second.id == "CHECKPOINT-0002"
    assert len(list_checkpoints(ot)) == 2


def test_checkpoint_git_metadata(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    ot = _ws(tmp_path)

    cp = create_checkpoint(tmp_path, ot, "git point")
    assert cp.kind == "git"
    assert cp.git_branch is not None
    assert cp.git_commit and len(cp.git_commit) >= 7
    assert cp.git_dirty is not None
