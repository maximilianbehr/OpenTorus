"""Tests for the task planner and pool (Milestone 12)."""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.agent.planner import RESEARCH_PIPELINE, plan
from opentorus.research.tasks import create_task, list_tasks, plan_tasks, tasks_dir
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_planner_trivial_goal_single_task() -> None:
    specs = plan("fix typo")
    assert len(specs) == 1
    assert specs[0][0] == "code"


def test_planner_substantial_goal_full_pipeline() -> None:
    specs = plan("prove the crouzeix conjecture for bounded analytic functions")
    categories = [c for c, _ in specs]
    assert categories == RESEARCH_PIPELINE
    assert set(categories) == {
        "literature",
        "code",
        "experiment",
        "analysis",
        "review",
        "report",
    }


def test_planner_non_research_goal_short_pipeline() -> None:
    specs = plan("investigate whether caching improves throughput under load")
    categories = [c for c, _ in specs]
    assert categories == ["literature", "code", "analysis"]


def test_planner_does_not_match_prove_inside_improves() -> None:
    specs = plan("investigate whether caching improves throughput under load")
    assert len(specs) == 3
    assert [c for c, _ in specs] == ["literature", "code", "analysis"]


def test_planner_simple_deliverable_two_tasks() -> None:
    specs = plan("write a short summary of matrix norms")
    assert len(specs) == 2
    assert specs[0][0] == "literature"
    assert specs[1][0] == "analysis"


def test_plan_tasks_creates_pool_and_cards(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    goal = "prove the crouzeix conjecture for bounded analytic functions"
    tasks = plan_tasks(ot, goal)
    assert len(tasks) == len(RESEARCH_PIPELINE)

    pool_path = tasks_dir(ot) / "TASK_POOL.json"
    assert pool_path.is_file()
    payload = json.loads(pool_path.read_text())
    assert len(payload) == len(tasks)

    for task in tasks:
        card = tasks_dir(ot) / f"{task.id}.md"
        assert card.is_file()
        assert task.goal in card.read_text()


def test_sequential_ids_and_persistence(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    first = create_task(ot, "code", "do a thing")
    second = create_task(ot, "analysis", "analyze a thing")
    assert first.id == "TASK-0001"
    assert second.id == "TASK-0002"
    stored = list_tasks(ot)
    assert [t.id for t in stored] == ["TASK-0001", "TASK-0002"]
    assert stored[0].verification_requirements
    assert stored[0].result_contract
