"""Tests for the git inspection tools (Milestone 5)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opentorus.tools.git import git_diff, git_status


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _has_git(), reason="git not available")


def test_status_non_repo(tmp_path: Path) -> None:
    result = git_status(tmp_path)
    assert result.is_repo is False
    assert "Not a git repository" in result.output


def test_status_and_diff_in_repo(tmp_path: Path) -> None:
    _git(["init"], tmp_path)
    _git(["config", "user.email", "t@example.com"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    (tmp_path / "f.txt").write_text("one\n", encoding="utf-8")
    _git(["add", "f.txt"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)

    status = git_status(tmp_path)
    assert status.is_repo is True

    (tmp_path / "f.txt").write_text("two\n", encoding="utf-8")
    diff = git_diff(tmp_path)
    assert diff.is_repo is True
    assert "-one" in diff.output and "+two" in diff.output
