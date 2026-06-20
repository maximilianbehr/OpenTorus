"""Tests for patch-lifecycle integration of agent edits (Milestone 26)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.patches import get_patch, list_patches, revert_patch
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class ScriptedProvider(BaseProvider):
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)

    def generate(self, messages, tools=None) -> ProviderResponse:
        if self._responses:
            return self._responses.pop(0)
        return ProviderResponse(kind="message", content="done")


def _write_then_done(path: str, content: str) -> ScriptedProvider:
    return ScriptedProvider(
        [
            ProviderResponse(
                kind="tool_call",
                content="",
                tool_name="write_file",
                tool_args={"path": path, "content": content},
            ),
            ProviderResponse(kind="message", content="done"),
        ]
    )


def _ws(tmp_path: Path):
    init_workspace(tmp_path)
    return tmp_path, workspace_dir(tmp_path)


def _loop(root, ot, provider):
    config = default_config()
    config.permissions.mode = "trusted"
    registry = build_default_registry(root, ot)
    return AgentLoop(root, ot, provider, registry, config)


def test_agent_edit_recorded_as_applied_patch(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    _loop(root, ot, _write_then_done("greet.py", "print('hi')\n")).run("create greet.py")

    patches = list_patches(ot)
    assert len(patches) == 1
    patch = patches[0]
    assert patch.status == "applied"
    assert "greet.py" in patch.files_changed
    # The diff artifact exists and is inspectable.
    assert (ot / patch.diff_path).is_file()
    assert (root / "greet.py").read_text() == "print('hi')\n"


def test_recorded_patch_is_revertable(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    (root / "f.txt").write_text("old\n", encoding="utf-8")
    _loop(root, ot, _write_then_done("f.txt", "new\n")).run("edit f.txt")

    patch = list_patches(ot)[0]
    assert patch.status == "applied"
    revert_patch(root, ot, patch.id)
    assert (root / "f.txt").read_text() == "old\n"
    assert get_patch(ot, patch.id).status == "reverted"


def test_no_patch_without_edits(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    _loop(root, ot, ScriptedProvider([ProviderResponse(kind="message", content="hi")])).run("hello")
    assert list_patches(ot) == []


def test_no_commit_made(tmp_path: Path) -> None:
    # Agent edits must never create git commits; the working tree changes only.
    import subprocess

    root, ot = _ws(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root,
        check=True,
    )
    before = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=root, capture_output=True, text=True
    ).stdout.strip()

    _loop(root, ot, _write_then_done("new.py", "x = 1\n")).run("add new.py")

    after = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=root, capture_output=True, text=True
    ).stdout.strip()
    assert before == after  # no new commits
    assert list_patches(ot)[0].status == "applied"
