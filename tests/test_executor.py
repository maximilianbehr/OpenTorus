"""Tests for plan execution (Milestone 24)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.executor import execute_plan
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.checkpoints import list_checkpoints
from opentorus.research.tasks import next_pending_task
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class MessageProvider(BaseProvider):
    """Always returns a final message (no tool calls)."""

    def __init__(self, text: str = "ok") -> None:
        self._text = text

    def generate(self, messages, tools=None) -> ProviderResponse:
        return ProviderResponse(kind="message", content=self._text)


class DeliverableProvider(BaseProvider):
    """One tool call per agent loop, chosen from the planned task category."""

    def generate(self, messages, tools=None) -> ProviderResponse:
        import re

        last_user = max(
            (i for i, m in enumerate(messages) if getattr(m, "role", None) == "user"),
            default=-1,
        )
        if any(getattr(m, "role", None) == "tool" for m in messages[last_user + 1 :]):
            return ProviderResponse(kind="message", content="done")
        category = "literature"
        for message in reversed(messages):
            if getattr(message, "role", None) != "system":
                continue
            text = str(getattr(message, "content", ""))
            if "Planned task execution" not in text:
                continue
            match = re.search(r"Category:\s*(\w+)", text)
            if match:
                category = match.group(1).lower()
            break
        if category == "code":
            return ProviderResponse(
                kind="tool_call",
                content="",
                tool_name="write_file",
                tool_args={"path": "scratch.py", "content": "# stub\n"},
            )
        if category == "experiment":
            return ProviderResponse(
                kind="tool_call",
                content="",
                tool_name="exp_run",
                tool_args={"exp_id": "EXP-0001"},
            )
        return ProviderResponse(
            kind="tool_call",
            content="",
            tool_name="memory_add",
            tool_args={"text": "literature note", "kind": "observations"},
        )


class AlternatingToolProvider(BaseProvider):
    """One ``memory_add`` tool call, then a final message — once per agent loop run."""

    def __init__(self) -> None:
        self._n = 0

    def generate(self, messages, tools=None) -> ProviderResponse:
        self._n += 1
        if self._n % 2 == 1:
            return ProviderResponse(
                kind="tool_call",
                content="",
                tool_name="memory_add",
                tool_args={"text": "literature note", "kind": "observations"},
            )
        return ProviderResponse(kind="message", content="done")


class FailingProvider(BaseProvider):
    def generate(self, messages, tools=None) -> ProviderResponse:
        from opentorus.errors import ProviderError

        raise ProviderError("boom")


def _ws(tmp_path: Path):
    init_workspace(tmp_path)
    return tmp_path, workspace_dir(tmp_path)


def _config():
    config = default_config()
    config.permissions.mode = "trusted"
    return config


def test_execute_plan_runs_all_tasks_and_checkpoints(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    outcome = execute_plan(
        root,
        ot,
        DeliverableProvider(),
        registry,
        _config(),
        goal="prove the crouzeix conjecture for bounded analytic functions",
        fresh=True,
        use_llm_planner=False,
        verify=False,
    )
    results = outcome.tasks
    assert len(results) >= 1
    assert all(r.status == "done" for r in results)
    assert all("chat-only" not in r.answer.lower() for r in results)
    assert len(list_checkpoints(ot)) == len(results)


def test_execute_plan_fails_chat_only_reply(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    outcome = execute_plan(
        root,
        ot,
        MessageProvider("What would you like to do?"),
        registry,
        _config(),
        goal="prove the crouzeix conjecture for bounded analytic functions",
        fresh=True,
        max_tasks=1,
        use_llm_planner=False,
    )
    assert outcome.tasks[0].status == "failed"
    answer = outcome.tasks[0].answer.lower()
    assert "contract not met" in answer


def test_execute_respects_max_tasks_and_is_resumable(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    config = _config()
    goal = "prove the crouzeix conjecture for bounded analytic functions"

    first = execute_plan(
        root,
        ot,
        DeliverableProvider(),
        registry,
        config,
        goal=goal,
        fresh=True,
        max_tasks=2,
        use_llm_planner=False,
        verify=False,
    )
    assert len(first.tasks) == 2
    assert next_pending_task(ot) is not None

    rest = execute_plan(root, ot, DeliverableProvider(), registry, config, verify=False)
    assert next_pending_task(ot) is None
    assert {r.task_id for r in first.tasks}.isdisjoint({r.task_id for r in rest.tasks})


def test_failing_task_marked_failed(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    outcome = execute_plan(
        root,
        ot,
        FailingProvider(),
        registry,
        _config(),
        goal="fix bug",
        max_tasks=1,
        use_llm_planner=False,
    )
    assert outcome.tasks[0].status == "failed"


class ToolThenMessageProvider(BaseProvider):
    """Calls ``memory_add`` once, then returns a final message."""

    def __init__(self) -> None:
        self._called = False

    def generate(self, messages, tools=None) -> ProviderResponse:
        if not self._called:
            self._called = True
            return ProviderResponse(
                kind="tool_call",
                content="",
                tool_name="memory_add",
                tool_args={"text": "note", "kind": "observations"},
            )
        return ProviderResponse(kind="message", content="done")


def test_execute_plan_reports_step_progress(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    lines: list[str] = []
    execute_plan(
        root,
        ot,
        ToolThenMessageProvider(),
        registry,
        _config(),
        goal="prove the crouzeix conjecture for bounded analytic functions",
        fresh=True,
        max_tasks=1,
        verify=False,
        use_llm_planner=False,
        progress=lines.append,
    )
    assert any("Planning" in line for line in lines)
    assert any("Planned" in line for line in lines)
    assert any("thinking" in line for line in lines)
    assert any("running memory_add" in line for line in lines)
    assert any("→ done" in line for line in lines)


def test_plan_aborts_when_model_never_calls_tools(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    outcome = execute_plan(
        root,
        ot,
        MessageProvider("Here is what I would do..."),
        registry,
        _config(),
        goal="prove the crouzeix conjecture for bounded analytic functions",
        fresh=True,
        max_tasks=8,
        use_llm_planner=False,
        verify=False,
    )
    # The circuit breaker stops after a couple of chat-only failures rather than
    # burning the entire pool.
    assert all(r.status == "failed" for r in outcome.tasks)
    assert len(outcome.tasks) <= 3
    assert "not reliably tool-calling" in outcome.idle_reason


def test_resume_with_no_tasks_raises(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, _config())
    import pytest

    from opentorus.errors import OpenTorusError

    with pytest.raises(OpenTorusError):
        execute_plan(root, ot, MessageProvider(), registry, _config())


def test_report_task_bootstraps_write_file_when_model_is_chat_only(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    from opentorus.agent.run_state import RunState, save_run_state
    from opentorus.research.tasks import create_task

    registry = build_default_registry(root, ot, _config())
    task = create_task(ot, "report", "write_file final investigation report.")
    save_run_state(
        ot,
        RunState(
            goal="sketch-and-solve report",
            session_id="sess-report",
            mode="plan",
            batch_task_ids=[task.id],
        ),
    )
    outcome = execute_plan(
        root,
        ot,
        MessageProvider("report assembled"),
        registry,
        _config(),
        verify=False,
        max_steps_per_task=6,
    )
    assert len(outcome.tasks) == 1
    assert outcome.tasks[0].status == "done"
    assert (root / "analysis.md").is_file()
