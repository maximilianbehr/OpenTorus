"""Tests for failed-task retry on plan resume."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.executor import execute_plan
from opentorus.agent.run_state import RunState, save_run_state
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.tasks import create_task, get_task, set_task_status
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class MessageProvider(BaseProvider):
    def generate(self, messages, tools=None) -> ProviderResponse:
        return ProviderResponse(kind="message", content="chat only")


class WriteProvider(BaseProvider):
    def generate(self, messages, tools=None) -> ProviderResponse:
        if any(getattr(m, "role", None) == "tool" for m in messages):
            return ProviderResponse(kind="message", content="done")
        return ProviderResponse(
            kind="tool_call",
            content="",
            tool_name="write_file",
            tool_args={"path": "note.md", "content": "ok\n"},
        )


def _ws(tmp_path: Path):
    init_workspace(tmp_path)
    return tmp_path, workspace_dir(tmp_path)


def _config():
    config = default_config()
    config.permissions.mode = "trusted"
    return config


def test_resume_retries_failed_tasks(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    task = create_task(ot, "report", "Write the report with write_file.")
    save_run_state(
        ot,
        RunState(goal="document outcome", session_id="sess", mode="plan", batch_task_ids=[task.id]),
    )
    set_task_status(ot, task.id, "failed")

    outcome = execute_plan(
        root,
        ot,
        WriteProvider(),
        registry,
        _config(),
        verify=False,
        retry_failed=True,
    )
    assert len(outcome.tasks) == 1
    assert outcome.tasks[0].status == "done"
    assert get_task(ot, task.id).status == "done"


def test_resume_without_retry_leaves_failed_idle(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    task = create_task(ot, "report", "Write the report.")
    save_run_state(
        ot,
        RunState(goal="document outcome", session_id="sess", mode="plan", batch_task_ids=[task.id]),
    )
    set_task_status(ot, task.id, "failed")

    outcome = execute_plan(
        root,
        ot,
        MessageProvider(),
        registry,
        _config(),
        verify=False,
        retry_failed=False,
    )
    assert outcome.tasks == []
    assert "failed" in outcome.idle_reason.lower()
    assert get_task(ot, task.id).status == "failed"
