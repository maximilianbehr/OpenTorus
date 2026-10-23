"""git_diff shows new/staged/untracked files, pages output, and runs no repo code (item 5)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opentorus.tools.git import git_diff

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path, *, commit: bool = True) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    if commit:
        (tmp_path / "base.txt").write_text("one\n", encoding="utf-8")
        _git(tmp_path, "add", "base.txt")
        _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_untracked_staged_and_modified_files_all_show(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "base.txt").write_text("two\n", encoding="utf-8")  # unstaged edit
    (repo / "staged.py").write_text("print('staged')\n", encoding="utf-8")
    _git(repo, "add", "staged.py")  # staged new file
    (repo / "agent_made.py").write_text("x = 1\ny = 2\n", encoding="utf-8")  # untracked
    (repo / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    (repo / "ignored.log").write_text("noise\n", encoding="utf-8")

    out = git_diff(repo).output
    assert "modified  base.txt" in out and "-one" in out and "+two" in out
    assert "added     staged.py" in out and "+print('staged')" in out
    assert "untracked agent_made.py  (+2 -0)" in out and "+y = 2" in out
    assert "b/ignored.log" not in out and "+noise" not in out


def test_repository_without_head(tmp_path: Path) -> None:
    repo = _repo(tmp_path, commit=False)
    (repo / "new.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "new.txt")
    (repo / "loose.txt").write_text("loose\n", encoding="utf-8")
    result = git_diff(repo)
    assert "no commit yet" in result.output
    assert "+hello" in result.output and "+loose" in result.output


def test_clean_repo_says_so(tmp_path: Path) -> None:
    assert "No changes" in git_diff(_repo(tmp_path)).output


def test_output_is_paged_with_an_explicit_more_marker(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "big.txt").write_text("".join(f"line {i}\n" for i in range(3000)), encoding="utf-8")
    _git(repo, "add", "big.txt")
    first = git_diff(repo, max_chars=2000)
    assert first.truncated and first.next_offset == 2000
    assert "Call git_diff with offset=2000" in first.output
    second = git_diff(repo, offset=first.next_offset or 0, max_chars=2000)
    assert second.output.startswith(git_diff(repo, max_chars=10**7).output[2000:2100])


def test_repo_configured_external_diff_and_textconv_never_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    marker = tmp_path / "PWNED"
    evil = tmp_path / "evil.sh"
    evil.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    evil.chmod(0o755)
    _git(repo, "config", "diff.external", str(evil))
    _git(repo, "config", "core.fsmonitor", str(evil))
    _git(repo, "config", "diff.evil.textconv", str(evil))
    (repo / ".gitattributes").write_text("*.txt diff=evil\n", encoding="utf-8")
    (repo / "base.txt").write_text("changed\n", encoding="utf-8")
    out = git_diff(repo).output
    assert "+changed" in out
    assert not marker.exists(), "git ran repository-configured code"


def test_path_filter(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / "b.txt").write_text("b\n", encoding="utf-8")
    out = git_diff(repo, "sub").output
    assert "sub/b.txt" in out and "a.txt" not in out


@pytest.mark.parametrize("commit", [True, False])
def test_opentorus_state_is_counted_not_shown(tmp_path: Path, commit: bool) -> None:
    """The workspace's own .opentorus/ state must not crowd out the agent's changes."""
    repo = _repo(tmp_path, commit=commit)
    state = repo / ".opentorus"
    state.mkdir()
    for i in range(30):
        (state / f"ledger{i}.jsonl").write_text("x" * 2000 + "\n", encoding="utf-8")
    (repo / "env_probe.py").write_text("print(1)\n", encoding="utf-8")
    out = git_diff(repo).output
    assert "env_probe.py" in out and "print(1)" in out
    assert "ledger0.jsonl" not in out
    assert "30 changed file(s) under .opentorus/" in out
    # Still reachable on request.
    assert "ledger0.jsonl" in git_diff(repo, ".opentorus").output
