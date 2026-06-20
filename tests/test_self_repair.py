"""Tests for edit verification and bounded self-repair (Milestone 25)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.agent.verify import verify_and_repair
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class MessageProvider(BaseProvider):
    def __init__(self, text: str = "ok") -> None:
        self._text = text

    def generate(self, messages, tools=None) -> ProviderResponse:
        return ProviderResponse(kind="message", content=self._text)


def _ws(tmp_path: Path):
    init_workspace(tmp_path)
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    return tmp_path, workspace_dir(tmp_path)


def _config(test_command):
    config = default_config()
    config.permissions.mode = "trusted"
    config.quality.test_command = test_command
    config.quality.lint_command = None
    config.quality.typecheck_command = None
    return config


def _loop(root, ot, config, provider=None):
    registry = build_default_registry(root, ot)
    loop = AgentLoop(root, ot, provider or MessageProvider(), registry, config)
    return loop


def test_no_verification_when_no_edits(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    config = _config("true")
    loop = _loop(root, ot, config)
    # loop.edited is False -> verification is skipped.
    outcome = verify_and_repair(loop, root, ot, config)
    assert outcome.status == "not_needed"


def test_passing_gates_after_edit(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    config = _config("true")  # always-passing gate
    loop = _loop(root, ot, config)
    loop.edited = True
    outcome = verify_and_repair(loop, root, ot, config)
    assert outcome.status == "passed"


def test_failing_gates_reported_honestly(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    config = _config("false")  # always-failing gate
    loop = _loop(root, ot, config)
    loop.edited = True
    outcome = verify_and_repair(loop, root, ot, config, max_repair_attempts=2)
    assert outcome.status == "failed"
    assert outcome.attempts == 2
    assert "Validation failed" in outcome.detail


def test_self_repair_succeeds_when_gate_starts_passing(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    # A gate that fails until a marker file exists; the repair "agent" creates it.
    marker = root / "fixed.flag"
    cmd = f"test -f {marker.name}"
    config = _config(cmd)

    class RepairProvider(BaseProvider):
        """On its repair turn, writes the marker file via a tool call, then stops."""

        def __init__(self) -> None:
            self._did_fix = False

        def generate(self, messages, tools=None) -> ProviderResponse:
            if not self._did_fix:
                self._did_fix = True
                return ProviderResponse(
                    kind="tool_call",
                    content="",
                    tool_name="write_file",
                    tool_args={"path": marker.name, "content": "ok"},
                )
            return ProviderResponse(kind="message", content="fixed")

    loop = _loop(root, ot, config, provider=RepairProvider())
    loop.edited = True
    outcome = verify_and_repair(loop, root, ot, config, max_repair_attempts=2)
    assert outcome.status == "repaired"
    assert outcome.attempts == 1
    assert marker.is_file()
