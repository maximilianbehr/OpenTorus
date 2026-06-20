"""Tests for agent prompt routing hints."""

from __future__ import annotations

from opentorus.agent.context import build_messages
from opentorus.agent.prompts import (
    TOOL_ROUTING_GUIDE,
    build_task_execution_prompt,
)
from opentorus.config import default_config
from opentorus.workspace import init_workspace, workspace_dir


def test_tool_routing_guide_mentions_anti_cycle() -> None:
    assert "Anti-cycle" in TOOL_ROUTING_GUIDE
    assert 'list_files(".")' in TOOL_ROUTING_GUIDE or 'list_files(".")' in TOOL_ROUTING_GUIDE
    assert "status" in TOOL_ROUTING_GUIDE
    assert "read_file" in TOOL_ROUTING_GUIDE
    assert "permission" in TOOL_ROUTING_GUIDE.lower()


def test_task_prompt_includes_category_tool_plan() -> None:
    prompt = build_task_execution_prompt(
        category="experiment",
        goal="Run validation suite",
        result_contract="An EXP-* entry",
        verification_requirements="Reproducible run",
    )
    assert "Tool plan:" in prompt
    assert "exp_run" in prompt
    assert "list_files" in prompt.lower()
    assert "One short exploration" in prompt


def test_build_messages_includes_tool_routing_guide(tmp_path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    messages = build_messages(tmp_path, ot, default_config(), ["status", "glob_files"])
    contents = [m.content for m in messages if m.role == "system"]
    assert any("Tool routing" in c for c in contents)
    assert any("Research artifacts" in c for c in contents)
