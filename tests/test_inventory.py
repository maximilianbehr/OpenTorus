"""Tests for research artifact inventory in agent context."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.context import build_context_summary
from opentorus.agent.inventory import format_artifact_inventory, gather_artifact_inventory
from opentorus.config import default_config
from opentorus.research.dossier.store import create_dossier
from opentorus.research.papers import add_paper
from opentorus.research.tasks import create_task
from opentorus.tools.base import ToolCall
from opentorus.tools.builtin import StatusTool
from opentorus.workspace import init_workspace, workspace_dir


def test_empty_inventory(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    inv = gather_artifact_inventory(tmp_path, ot)
    assert inv.num_papers == 0
    assert inv.num_dossiers == 0
    assert inv.has_python_project is False
    text = format_artifact_inventory(inv)
    assert "papers: none" in text
    assert "do not browse .opentorus/" in text


def test_inventory_lists_artifacts(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    from opentorus.research.papers import acquire_paper
    from opentorus.research.sources.base import SourceRecord

    acquire_paper(
        ot,
        SourceRecord(source="arxiv", title="Sign", arxiv_id="2504.01500"),
        downloader=lambda u: b"%PDF fake",
    )
    create_dossier(ot, "Is the ratio bounded?", tags=["PAPER-0001", "label:3.1"])
    create_task(ot, "literature", "Survey related work on the Crouzeix conjecture.")
    inv = gather_artifact_inventory(tmp_path, ot)
    assert inv.num_papers == 1
    assert inv.num_dossiers == 1
    assert "PAPER-0001" in inv.papers[0]
    assert 'fetch="2504.01500"' in inv.papers[0]
    assert "PROBLEM-0001" in inv.dossiers[0]
    assert inv.task_counts.get("proposed", 0) >= 1


def test_context_summary_includes_inventory(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    add_paper(ot, "https://example.com/paper.pdf")
    summary = build_context_summary(tmp_path, ot, default_config(), ["status", "paper_list"])
    assert "Research artifacts" in summary
    assert "PAPER-0001" in summary
    assert "paper_list" in summary


def test_inventory_lists_root_python_scripts(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    (tmp_path / "search_pi2.py").write_text("# probe\n", encoding="utf-8")
    inv = gather_artifact_inventory(tmp_path, ot)
    assert "search_pi2.py" in inv.script_paths
    text = format_artifact_inventory(inv)
    assert "search_pi2.py" in text

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    add_paper(ot, "https://example.com/paper.pdf")
    tool = StatusTool(tmp_path, ot)
    result = tool.run(ToolCall(id="1", name="status", args={}))
    assert result.ok
    assert "Research artifacts:" in result.content
    assert "PAPER-0001" in result.content
