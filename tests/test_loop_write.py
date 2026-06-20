"""Tests for guarded write/command tools in the agent loop (Milestone 23)."""

from __future__ import annotations

from pathlib import Path

from opentorus.actions import list_actions
from opentorus.agent.loop import AgentLoop
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class ScriptedProvider(BaseProvider):
    """Emits a queued list of responses, one per ``generate`` call."""

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)

    def generate(self, messages, tools=None) -> ProviderResponse:
        if self._responses:
            return self._responses.pop(0)
        return ProviderResponse(kind="message", content="done")


def _tool_then_done(name: str, args: dict) -> ScriptedProvider:
    return ScriptedProvider(
        [
            ProviderResponse(kind="tool_call", content="", tool_name=name, tool_args=args),
            ProviderResponse(kind="message", content="done"),
        ]
    )


def _ws(tmp_path: Path):
    init_workspace(tmp_path)
    return tmp_path, workspace_dir(tmp_path)


def _loop(root, ot, provider, mode="trusted", style="normal", review=False, confirm=None):
    config = default_config()
    config.permissions.mode = mode
    config.agent.style = style
    config.agent.mode = "review" if review else "normal"
    registry = build_default_registry(root, ot)
    return AgentLoop(root, ot, provider, registry, config, confirm=confirm)


def test_write_file_executes_in_trusted(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    provider = _tool_then_done("write_file", {"path": "hello.txt", "content": "hi\n"})
    _loop(root, ot, provider, mode="trusted").run("create hello.txt")
    assert (root / "hello.txt").read_text() == "hi\n"
    last_write = [a for a in list_actions(ot) if a.tool_name == "write_file"][-1]
    assert last_write.ok is True
    assert last_write.permission_decision.get("allowed") is True


def test_write_blocked_in_safe_mode(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    provider = _tool_then_done("write_file", {"path": "nope.txt", "content": "x"})
    _loop(root, ot, provider, mode="safe").run("write nope")
    assert not (root / "nope.txt").exists()


def test_write_blocked_in_review_mode(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    provider = _tool_then_done("write_file", {"path": "nope.txt", "content": "x"})
    _loop(root, ot, provider, mode="trusted", review=True).run("write nope")
    assert not (root / "nope.txt").exists()


def test_write_requires_confirmation_in_ask_mode(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    # No confirm callback -> declined.
    provider = _tool_then_done("write_file", {"path": "a.txt", "content": "x"})
    _loop(root, ot, provider, mode="ask").run("write a")
    assert not (root / "a.txt").exists()

    # With an approving callback -> written.
    provider2 = _tool_then_done("write_file", {"path": "a.txt", "content": "x"})
    _loop(root, ot, provider2, mode="ask", confirm=lambda d, desc, scope=None: True).run("write a")
    assert (root / "a.txt").read_text() == "x"


def test_dangerous_command_always_blocked(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    provider = _tool_then_done("run_shell", {"command": "rm -rf /"})
    # Even trusted + autonomous + approving confirm must not run a dangerous command.
    loop = _loop(
        root,
        ot,
        provider,
        mode="trusted",
        style="autonomous",
        confirm=lambda d, desc, scope=None: True,
    )
    loop.run("danger")
    blocked = [a for a in list_actions(ot) if a.tool_name == "run_shell"][-1]
    assert blocked.ok is False
    assert blocked.permission_decision.get("risk_level") == "blocked"


def test_run_shell_executes_harmless_in_trusted(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    provider = _tool_then_done("run_shell", {"command": "echo hello"})
    answer = _loop(root, ot, provider, mode="trusted").run("say hello")
    assert answer == "done"
    entry = [a for a in list_actions(ot) if a.tool_name == "run_shell"][-1]
    assert entry.ok is True
