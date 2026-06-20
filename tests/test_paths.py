"""Tests for workspace path safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import PathTraversalError
from opentorus.paths import (
    find_workspace_root,
    looks_like_uninitialized_project,
    resolve_cli_workspace_root,
    resolve_workspace_path,
)
from opentorus.workspace import init_workspace


def test_resolves_relative_path_inside_workspace(tmp_path: Path) -> None:
    resolved = resolve_workspace_path(tmp_path, "src/module.py")
    assert resolved == (tmp_path / "src" / "module.py").resolve()


def test_resolves_workspace_root_itself(tmp_path: Path) -> None:
    assert resolve_workspace_path(tmp_path, ".") == tmp_path.resolve()


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_workspace_path(tmp_path, "../secret")


def test_rejects_nested_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_workspace_path(tmp_path, "a/../../b")


def test_rejects_absolute_path_outside(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_workspace_path(tmp_path, "/etc/passwd")


def test_find_workspace_root(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_workspace_root(nested) == tmp_path.resolve()


def test_find_workspace_root_none(tmp_path: Path) -> None:
    assert find_workspace_root(tmp_path) is None


def test_looks_like_uninitialized_project(tmp_path: Path) -> None:
    assert not looks_like_uninitialized_project(tmp_path)
    (tmp_path / "papers").mkdir()
    assert looks_like_uninitialized_project(tmp_path)
    init_workspace(tmp_path)
    assert not looks_like_uninitialized_project(tmp_path)


def test_resolve_cli_workspace_root_uses_local_opentorus(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    assert resolve_cli_workspace_root(tmp_path) == tmp_path.resolve()


def test_resolve_cli_workspace_root_allows_project_subdir(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    nested = tmp_path / "src"
    nested.mkdir()
    assert resolve_cli_workspace_root(nested) == tmp_path.resolve()


def test_resolve_cli_workspace_root_rejects_uninitialized_papers_dir(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    sibling = tmp_path / "other"
    sibling.mkdir()
    (sibling / "papers").mkdir()
    assert resolve_cli_workspace_root(sibling) is None


def test_resolve_cli_workspace_root_rejects_home_from_subdir(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("opentorus.paths.Path.home", lambda: home)
    init_workspace(home)
    child = home / "project"
    child.mkdir()
    assert resolve_cli_workspace_root(home) == home.resolve()
    assert resolve_cli_workspace_root(child) is None
