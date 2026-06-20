"""Tests for planned-task bootstrap and session sanitization."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.context import _sanitize_session_history, build_messages
from opentorus.agent.session import SessionMessage, append_message
from opentorus.agent.task_bootstrap import bootstrap_tool_for_task
from opentorus.config import default_config
from opentorus.research.tasks import create_task
from opentorus.workspace import init_workspace, workspace_dir


def test_sanitize_session_history_drops_recovery_noise() -> None:
    history = [
        SessionMessage(role="user", content="Run exp_run for PROBLEM-0001"),
        SessionMessage(role="assistant", content=""),
        SessionMessage(
            role="user",
            content="This is a planned task that requires tool use to produce a deliverable.",
        ),
        SessionMessage(role="assistant", content="ok"),
    ]
    cleaned = _sanitize_session_history(history)
    assert len(cleaned) == 2
    assert cleaned[0].content.startswith("Run exp_run")
    assert cleaned[1].content == "ok"


def test_recovery_hint_is_ephemeral_not_in_session(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    append_message(ot, SessionMessage(role="user", content="task goal"))
    messages = build_messages(
        tmp_path,
        ot,
        default_config(),
        ["status"],
        recovery_hint="Attempt 1: call exp_run now.",
    )
    assert messages[-1].content.startswith("Attempt 1")
    from opentorus.agent.session import read_messages

    assert len(read_messages(ot)) == 1


def test_bootstrap_dossier_experiment_uses_run_shell(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    from opentorus.research.dossier.experiments import create_experiment
    from opentorus.research.dossier.store import create_dossier

    dossier = create_dossier(ot, "Test problem.", title="Test")
    create_experiment(
        ot,
        dossier.id,
        title="validation",
        command="echo ok",
    )
    task = create_task(ot, "experiment", f"Run validation tests for {dossier.id} with exp_run.")
    boot = bootstrap_tool_for_task(task, tmp_path, ot)
    assert boot is not None
    assert boot[0] == "run_shell"
    assert "run.sh" in boot[1]["command"]


def test_bootstrap_analysis_proof_uses_proof_write(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    from opentorus.research.dossier.store import create_dossier

    create_dossier(ot, "Prove X.", title="Test")
    task = create_task(ot, "analysis", "Write natural-language proof for PROBLEM-0001.")
    boot = bootstrap_tool_for_task(task, tmp_path, ot)
    assert boot is not None
    assert boot[0] == "proof_write"
    assert boot[1]["problem_id"] == "PROBLEM-0001"


def test_report_task_bootstrap_writes_analysis_md(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    task = create_task(ot, "report", "Document outcome with write_file.")
    boot = bootstrap_tool_for_task(task, tmp_path, ot)
    assert boot is not None
    assert boot[0] == "write_file"
    assert boot[1]["path"] == "analysis.md"
