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


def test_inventory_lists_recent_claims_with_statements(tmp_path: Path) -> None:
    # Claims must appear with id + status + statement (not just a count) so the
    # agent does not forget or doubt claims it created earlier in a long run.
    from opentorus.research.claims import new_claim

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    new_claim(ot, "The restart-cost ratio is bounded by two.")
    inv = gather_artifact_inventory(tmp_path, ot)
    assert inv.workspace_claims == 1
    assert any("CLAIM-0001" in line and "restart-cost ratio" in line for line in inv.claim_lines)
    text = format_artifact_inventory(inv)
    assert "CLAIM: CLAIM-0001" in text
    assert "restart-cost ratio" in text


def test_build_messages_anchors_goal_as_system_message(tmp_path: Path) -> None:
    # The run's task must be anchored as a persistent system message so it does not
    # scroll out of the windowed history on a long autonomous run.
    from opentorus.agent.context import build_messages

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    goal = "Produce a natural-language proof sketch for PROBLEM-0002 with explicit gaps."
    messages = build_messages(tmp_path, ot, default_config(), ["status"], goal=goal)
    system_text = "\n".join(m.content for m in messages if m.role == "system")
    assert "Current task" in system_text
    assert "PROBLEM-0002" in system_text
