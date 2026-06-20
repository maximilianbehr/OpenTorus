"""Tests for planned-task result contracts."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.task_validation import snapshot_artifacts, validate_task_contract
from opentorus.research.memory import add_memory
from opentorus.research.tasks import create_task
from opentorus.workspace import init_workspace, workspace_dir


def test_literature_contract_accepts_memory_add(tmp_path: Path) -> None:
    root = tmp_path
    init_workspace(root)
    ot = workspace_dir(root)
    before = snapshot_artifacts(root, ot)
    add_memory(ot, "observations", "read paper X")
    after = snapshot_artifacts(root, ot)
    after.tool_names = ["memory_add"]
    task = create_task(ot, "literature", "Survey papers on topic T")
    check = validate_task_contract(task, before, after, tool_calls=1, edited=False)
    assert check.ok


def test_code_contract_requires_edit_or_write(tmp_path: Path) -> None:
    root = tmp_path
    init_workspace(root)
    ot = workspace_dir(root)
    before = snapshot_artifacts(root, ot)
    after = snapshot_artifacts(root, ot)
    after.tool_names = ["status"]
    task = create_task(ot, "code", "Implement solver")
    check = validate_task_contract(task, before, after, tool_calls=1, edited=False)
    assert not check.ok
