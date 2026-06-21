"""Tests for atomic writes, checkpoint restore, and doctor backend reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.atomicio import atomic_write_text
from opentorus.errors import OpenTorusError


def test_atomic_write_replaces_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "ledger.jsonl"
    atomic_write_text(target, "a\nb\n")
    assert target.read_text() == "a\nb\n"
    atomic_write_text(target, "c\n")
    assert target.read_text() == "c\n"
    # No stray temp files left behind.
    assert [p.name for p in tmp_path.iterdir()] == ["ledger.jsonl"]


def test_atomic_write_failure_preserves_original(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    atomic_write_text(target, "original")

    class Boom:
        def __str__(self) -> str:
            raise RuntimeError("cannot stringify")

    with pytest.raises(Exception):  # noqa: B017 - any failure must not corrupt the file
        atomic_write_text(target, Boom())  # type: ignore[arg-type]
    assert target.read_text() == "original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.txt"]


def test_checkpoint_restore_manifest_diff(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # Outside a git repo, restore reports the file diff since the checkpoint.
    from opentorus.research.checkpoints import create_checkpoint, restore_checkpoint
    from opentorus.workspace import init_workspace, workspace_dir

    root = tmp_path
    init_workspace(root)
    ot = workspace_dir(root)
    (root / "a.txt").write_text("x")
    monkeypatch.setattr("opentorus.research.checkpoints._is_repo", lambda _root: False)
    cp = create_checkpoint(root, ot, "before edits")
    assert cp.kind == "manifest"
    (root / "b.txt").write_text("y")  # add a file after the checkpoint
    result = restore_checkpoint(root, ot, cp.id)
    assert result.applied is False
    assert "b.txt" in result.added


def test_checkpoint_restore_unknown_id(tmp_path: Path) -> None:
    from opentorus.research.checkpoints import restore_checkpoint
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    with pytest.raises(OpenTorusError):
        restore_checkpoint(tmp_path, ot, "CHECKPOINT-9999")


def test_doctor_reports_verifier_and_execution(tmp_path: Path) -> None:
    from opentorus.config import default_config
    from opentorus.doctor import run_doctor
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    names = {c.name for c in run_doctor(tmp_path, ot, default_config())}
    assert "verifiers" in names
    assert "execution" in names
