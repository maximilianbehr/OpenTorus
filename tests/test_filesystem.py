"""Tests for path-safe filesystem tools (Milestone 5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError, PathTraversalError, PermissionDeniedError
from opentorus.tools.filesystem import (
    apply_patch,
    glob_files,
    grep,
    list_files,
    patch_preview,
    read_file,
    write_file,
)


def test_list_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    assert set(list_files(tmp_path, ".")) == {"a.txt", "sub"}


def test_read_file_full_and_range(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("l1\nl2\nl3\nl4\n", encoding="utf-8")
    assert read_file(tmp_path, "a.txt").splitlines() == ["l1", "l2", "l3", "l4"]
    assert read_file(tmp_path, "a.txt", start=2, end=3) == "l2\nl3"


def test_write_file_inside_workspace(tmp_path: Path) -> None:
    written = write_file(tmp_path, "sub/new.txt", "hello")
    assert written.read_text(encoding="utf-8") == "hello"


def test_write_file_outside_workspace_rejected(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        write_file(tmp_path, "../escape.txt", "nope")


def test_read_sensitive_file_blocked(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    with pytest.raises(PermissionDeniedError):
        read_file(tmp_path, ".env")
    # explicit opt-in works
    assert "SECRET=1" in read_file(tmp_path, ".env", allow_sensitive=True)


def test_read_file_binary_raises_clear_error(tmp_path: Path) -> None:
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4\xbf")
    with pytest.raises(OpenTorusError, match="UTF-8") as exc:
        read_file(tmp_path, "paper.pdf")
    assert "paper_fetch" in str(exc.value)


def test_grep_finds_matches(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "y.py").write_text("bar = 2\n", encoding="utf-8")
    results = grep(tmp_path, r"def \w+")
    assert any(r[0] == "x.py" for r in results)
    assert all("y.py" != r[0] for r in results)


def test_apply_patch_replaces_exact_text(tmp_path: Path) -> None:
    (tmp_path / "c.py").write_text("value = 1\n", encoding="utf-8")
    preview = apply_patch(tmp_path, "c.py", "value = 1", "value = 2")
    assert "value = 2" in (tmp_path / "c.py").read_text(encoding="utf-8")
    assert "-value = 1" in preview and "+value = 2" in preview


def test_apply_patch_missing_text_raises(tmp_path: Path) -> None:
    (tmp_path / "c.py").write_text("value = 1\n", encoding="utf-8")
    with pytest.raises(OpenTorusError):
        apply_patch(tmp_path, "c.py", "not here", "x")


def test_apply_patch_ambiguous_text_raises(tmp_path: Path) -> None:
    (tmp_path / "c.py").write_text("x\nx\n", encoding="utf-8")
    with pytest.raises(OpenTorusError):
        apply_patch(tmp_path, "c.py", "x", "y")


def test_patch_preview_is_unified_diff() -> None:
    preview = patch_preview("a\n", "b\n", "f.txt")
    assert "--- a/f.txt" in preview
    assert "+++ b/f.txt" in preview


def test_list_files_hides_noise(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".DS_Store").write_bytes(b"noise")
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_path / ".mypy_cache").mkdir()
    (tmp_path / ".mypy_cache" / "x").write_text("cache", encoding="utf-8")
    assert set(list_files(tmp_path, ".")) == {"main.py", "src"}


def test_list_files_blocks_opentorus_root(tmp_path: Path) -> None:
    ot = tmp_path / ".opentorus"
    ot.mkdir()
    (ot / "session.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(OpenTorusError, match="internal OpenTorus"):
        list_files(tmp_path, ".opentorus")


def test_read_file_blocks_scaffold(tmp_path: Path) -> None:
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    with pytest.raises(OpenTorusError, match="scaffolding"):
        read_file(tmp_path, ".gitkeep")


def test_glob_files_skips_caches(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "ignored.py").write_text("x", encoding="utf-8")
    assert glob_files(tmp_path, "**/*.py") == ["app.py"]


def test_read_file_allows_task_card(tmp_path: Path) -> None:
    tasks = tmp_path / ".opentorus" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "TASK-0001.md").write_text("# TASK-0001\nGoal here.\n", encoding="utf-8")
    text = read_file(tmp_path, ".opentorus/tasks/TASK-0001.md")
    assert "Goal here." in text


def test_list_files_allows_tasks_dir(tmp_path: Path) -> None:
    tasks = tmp_path / ".opentorus" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "TASK-0001.md").write_text("# TASK\n", encoding="utf-8")
    assert list_files(tmp_path, ".opentorus/tasks") == ["TASK-0001.md"]


def test_glob_files_includes_task_cards(tmp_path: Path) -> None:
    tasks = tmp_path / ".opentorus" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "TASK-0001.md").write_text("# TASK\n", encoding="utf-8")
    matches = glob_files(tmp_path, "**/*.md")
    assert ".opentorus/tasks/TASK-0001.md" in matches


def test_read_file_allows_dossier_statement(tmp_path: Path) -> None:
    dossier = tmp_path / ".opentorus" / "problems" / "PROBLEM-0001"
    dossier.mkdir(parents=True)
    (dossier / "statement.md").write_text("# Problem\nTest.\n", encoding="utf-8")
    text = read_file(tmp_path, ".opentorus/problems/PROBLEM-0001/statement.md")
    assert "Test." in text


def test_list_files_allows_problems_index(tmp_path: Path) -> None:
    problems = tmp_path / ".opentorus" / "problems" / "PROBLEM-0001"
    problems.mkdir(parents=True)
    (problems / "statement.md").write_text("# Problem\n", encoding="utf-8")
    assert list_files(tmp_path, ".opentorus/problems") == ["PROBLEM-0001"]
    assert "statement.md" in list_files(tmp_path, ".opentorus/problems/PROBLEM-0001")


def test_glob_files_includes_dossier_markdown(tmp_path: Path) -> None:
    dossier = tmp_path / ".opentorus" / "problems" / "PROBLEM-0001"
    dossier.mkdir(parents=True)
    (dossier / "statement.md").write_text("# Problem\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("x=1\n", encoding="utf-8")
    matches = glob_files(tmp_path, "**/*.md")
    assert ".opentorus/problems/PROBLEM-0001/statement.md" in matches
    assert "app.py" not in matches


def test_read_file_resolves_unpadded_problem_id(tmp_path: Path) -> None:
    from opentorus.research.dossier.store import create_dossier
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    create_dossier(workspace_dir(tmp_path), "Polynomial sign approximation problem.")
    text = read_file(tmp_path, ".opentorus/problems/PROBLEM-1/statement.md")
    assert "Polynomial sign approximation" in text
    assert "resolved to PROBLEM-0001" in text


def test_read_file_unknown_problem_lists_valid_ids(tmp_path: Path) -> None:
    from opentorus.research.dossier.store import create_dossier
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    create_dossier(workspace_dir(tmp_path), "Only dossier.")
    with pytest.raises(OpenTorusError) as exc:
        read_file(tmp_path, ".opentorus/problems/PROBLEM-9027/statement.md")
    assert "PROBLEM-0001" in str(exc.value)
    assert "Existing problem dossiers" in str(exc.value)


def test_read_file_paper_pdf_points_to_paper_read(tmp_path: Path) -> None:
    # Reading a cached paper PDF under .opentorus/papers/ is refused, and the
    # message must point to paper_read (the correct tool), not a generic hint.
    papers = tmp_path / ".opentorus" / "papers" / "PAPER-0002"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(OpenTorusError, match=r'paper_read\("PAPER-0002"\)'):
        read_file(tmp_path, ".opentorus/papers/PAPER-0002/paper.pdf")


def test_write_file_blocks_internal_opentorus(tmp_path: Path) -> None:
    # M3: write_file must refuse the papers cache / internal state, like the read guard.
    (tmp_path / ".opentorus" / "papers" / "PAPER-0001").mkdir(parents=True)
    with pytest.raises(OpenTorusError, match="internal OpenTorus"):
        write_file(tmp_path, ".opentorus/papers/PAPER-0001/paper.pdf", "x")


def test_write_file_allows_dossier_and_project_files(tmp_path: Path) -> None:
    (tmp_path / ".opentorus" / "problems" / "PROBLEM-0001").mkdir(parents=True)
    write_file(tmp_path, ".opentorus/problems/PROBLEM-0001/notes.md", "ok")  # dossier file
    write_file(tmp_path, "analysis.md", "ok")  # project file outside .opentorus
