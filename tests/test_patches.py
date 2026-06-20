"""Tests for patch artifacts (Milestone 18)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.patches import (
    apply_patch_artifact,
    get_patch,
    list_patches,
    propose_patch,
    reject_patch,
    revert_patch,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_propose_stores_artifact_without_writing(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    (tmp_path / "f.txt").write_text("old\n", encoding="utf-8")
    patch = propose_patch(tmp_path, ot, [("f.txt", "new\n")], "improve f")
    assert patch.id == "PATCH-0001"
    assert patch.status == "proposed"
    assert patch.files_changed == ["f.txt"]
    # Proposing must NOT modify the working tree.
    assert (tmp_path / "f.txt").read_text() == "old\n"
    assert (ot / patch.diff_path).is_file()
    assert (ot / patch.metadata_path).is_file()


def test_apply_then_revert_roundtrip(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    (tmp_path / "f.txt").write_text("old\n", encoding="utf-8")
    patch = propose_patch(tmp_path, ot, [("f.txt", "new\n")], "improve f")

    applied = apply_patch_artifact(tmp_path, ot, patch.id)
    assert applied.status == "applied"
    assert applied.applied_at is not None
    assert (tmp_path / "f.txt").read_text() == "new\n"

    reverted = revert_patch(tmp_path, ot, patch.id)
    assert reverted.status == "reverted"
    assert (tmp_path / "f.txt").read_text() == "old\n"


def test_reject_keeps_files_untouched(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    (tmp_path / "f.txt").write_text("old\n", encoding="utf-8")
    patch = propose_patch(tmp_path, ot, [("f.txt", "new\n")], "improve f")
    rejected = reject_patch(ot, patch.id)
    assert rejected.status == "rejected"
    assert (tmp_path / "f.txt").read_text() == "old\n"


def test_new_file_patch(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    patch = propose_patch(tmp_path, ot, [("created.txt", "hi\n")], "add file")
    apply_patch_artifact(tmp_path, ot, patch.id)
    assert (tmp_path / "created.txt").read_text() == "hi\n"
    revert_patch(tmp_path, ot, patch.id)
    assert (tmp_path / "created.txt").read_text() == ""


def test_invalid_status_transitions(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    (tmp_path / "f.txt").write_text("old\n", encoding="utf-8")
    patch = propose_patch(tmp_path, ot, [("f.txt", "new\n")], "x")
    # Cannot revert a patch that was never applied.
    with pytest.raises(OpenTorusError):
        revert_patch(tmp_path, ot, patch.id)
    apply_patch_artifact(tmp_path, ot, patch.id)
    # Cannot reject an already-applied patch.
    with pytest.raises(OpenTorusError):
        reject_patch(ot, patch.id)
    # Cannot apply twice.
    with pytest.raises(OpenTorusError):
        apply_patch_artifact(tmp_path, ot, patch.id)


def test_empty_patch_rejected(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        propose_patch(tmp_path, ot, [], "nothing")


def test_get_and_list(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    (tmp_path / "f.txt").write_text("a\n", encoding="utf-8")
    propose_patch(tmp_path, ot, [("f.txt", "b\n")], "one")
    propose_patch(tmp_path, ot, [("f.txt", "c\n")], "two")
    assert len(list_patches(ot)) == 2
    assert get_patch(ot, "PATCH-0002").reason == "two"
