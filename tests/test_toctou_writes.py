"""TOCTOU-safe writes (6i): a symlink swapped in after the path check is refused."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.tools import filesystem
from opentorus.tools.filesystem import apply_patch, safe_write_text, write_file

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("precious\n", encoding="utf-8")
    return root, outside


def test_symlink_swapped_in_after_the_check_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, outside = _setup(tmp_path)
    (root / "notes.md").write_text("mine\n", encoding="utf-8")
    real_parts = filesystem._relative_parts  # noqa: SLF001

    def check_then_swap(r: Path, target: Path) -> tuple[str, ...]:
        parts = real_parts(r, target)  # the check sees a regular file ...
        target.unlink()
        target.symlink_to(outside)  # ... then an attacker swaps in a symlink
        return parts

    monkeypatch.setattr(filesystem, "_relative_parts", check_then_swap)
    with pytest.raises(OpenTorusError, match="symbolic link"):
        write_file(root, "notes.md", "overwritten\n")
    assert outside.read_text(encoding="utf-8") == "precious\n"


def test_symlinked_parent_escaping_the_workspace_is_refused(tmp_path: Path) -> None:
    root, outside = _setup(tmp_path)
    (root / "link").symlink_to(tmp_path)  # a directory symlink pointing out of root
    target = root / "link" / "outside.txt"
    with pytest.raises(OpenTorusError, match="outside the workspace"):
        safe_write_text(root, target, "link/outside.txt", "overwritten\n")
    assert outside.read_text(encoding="utf-8") == "precious\n"


def test_final_symlink_inside_workspace_is_refused_too(tmp_path: Path) -> None:
    root, _ = _setup(tmp_path)
    (root / "real.txt").write_text("a\n", encoding="utf-8")
    (root / "alias.txt").symlink_to(root / "real.txt")
    with pytest.raises(OpenTorusError, match="symbolic link"):
        safe_write_text(root, root / "alias.txt", "alias.txt", "b\n")
    assert (root / "real.txt").read_text(encoding="utf-8") == "a\n"


def test_sensitive_target_is_refused_at_use(tmp_path: Path) -> None:
    root, _ = _setup(tmp_path)
    with pytest.raises(OpenTorusError, match="sensitive"):
        safe_write_text(root, root / ".env", ".env", "OPENAI_API_KEY=x\n")
    assert not (root / ".env").exists() or (root / ".env").read_text() == ""


def test_apply_patch_uses_the_safe_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, outside = _setup(tmp_path)
    (root / "f.py").write_text("x = 1\n", encoding="utf-8")
    calls: list[str] = []
    real = filesystem.safe_write_text

    def spy(r: Path, target: Path, user_path: str, content: str) -> None:
        calls.append(user_path)
        real(r, target, user_path, content)

    monkeypatch.setattr(filesystem, "safe_write_text", spy)
    apply_patch(root, "f.py", "x = 1", "x = 2")
    assert calls == ["f.py"]
    assert (root / "f.py").read_text(encoding="utf-8") == "x = 2\n"


def test_ordinary_writes_still_work(tmp_path: Path) -> None:
    root, _ = _setup(tmp_path)
    write_file(root, "a/b/c.txt", "hello\n")
    assert (root / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "hello\n"
    write_file(root, "a/b/c.txt", "hi\n")  # shorter content truncates correctly
    assert (root / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "hi\n"
