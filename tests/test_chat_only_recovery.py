"""Tests for planned-task chat-only recovery in the agent loop."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.tasks import create_task
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class ChatThenToolProvider(BaseProvider):
    def __init__(self) -> None:
        self._turn = 0

    def generate(self, messages, tools=None) -> ProviderResponse:
        self._turn += 1
        if self._turn == 1:
            return ProviderResponse(kind="message", content="I'll write that now.")
        return ProviderResponse(
            kind="tool_call",
            content="",
            tool_name="write_file",
            tool_args={"path": "out.md", "content": "# done\n"},
        )


def test_planned_task_recovers_from_chat_only_reply(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot, default_config())
    task = create_task(ot, "report", "Write out.md")
    config = default_config()
    config.permissions.mode = "trusted"
    loop = AgentLoop(tmp_path, ot, ChatThenToolProvider(), registry, config)
    loop._task_id = task.id
    answer = loop.run(task.goal)
    assert loop.tool_calls_this_run >= 1
    assert answer
