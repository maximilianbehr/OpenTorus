"""Tests for UI#3 (per-step cost surfacing) and UI#2 (interruptibility)."""

from __future__ import annotations

import logging
from pathlib import Path

from typer.testing import CliRunner

from opentorus.agent.loop import AgentLoop
from opentorus.cli import app
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.usage import format_usage_line
from opentorus.ux import format_interrupt_message
from opentorus.workspace import init_workspace, workspace_dir

runner = CliRunner()


# --- UI#3 cost surfacing -----------------------------------------------------


def test_format_usage_line_local_is_free() -> None:
    line = format_usage_line("mock", "mock", 1500, 500)
    assert "2.0k tok" in line
    assert "$0 (local)" in line


def test_format_usage_line_paid_shows_cost() -> None:
    line = format_usage_line("openai", "gpt-4o", 1000, 1000, session_cost=0.12)
    assert "~$" in line
    assert "session ~$0.1200" in line


def test_loop_logs_per_step_usage(tmp_path: Path, caplog) -> None:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    loop = AgentLoop(tmp_path, ot_dir, MockProvider(), registry, default_config())
    with caplog.at_level(logging.INFO, logger="opentorus.agent.loop"):
        loop.run("hello there")
    assert any("tok" in rec.message for rec in caplog.records)


def test_tool_call_turn_counts_output_tokens(tmp_path: Path, caplog) -> None:
    # A tool-call turn's output is the tool name + args (content is empty there),
    # so the "out" count must not always be zero.
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    loop = AgentLoop(tmp_path, ot_dir, MockProvider(), registry, default_config())
    with caplog.at_level(logging.INFO, logger="opentorus.agent.loop"):
        loop.run("show me the status")  # drives a status tool call
    usage_lines = [r.message for r in caplog.records if "tok" in r.message]
    assert usage_lines
    # At least one logged turn reports a non-zero output-token count.
    assert any("0 out)" not in line for line in usage_lines)


# --- UI#2 interruptibility ---------------------------------------------------


def test_loop_logs_session_total_at_end(tmp_path: Path, caplog) -> None:
    # At the end of a run, a Σ line reports the cumulative input/output tokens.
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    loop = AgentLoop(tmp_path, ot_dir, MockProvider(), registry, default_config())
    with caplog.at_level(logging.INFO, logger="opentorus.agent.loop"):
        loop.run("show me the status")
    totals = [r.message for r in caplog.records if r.message.startswith("Σ")]
    assert len(totals) == 1
    assert "in /" in totals[0] and "out)" in totals[0]


def test_format_usage_total_sums() -> None:
    from opentorus.usage import UsageSummary, format_usage_total

    line = format_usage_total(
        UsageSummary(turns=3, prompt_tokens=9500, completion_tokens=2500, total_tokens=12000)
    )
    assert "3 turn(s)" in line
    assert "9.5k in / 2.5k out" in line


def test_format_interrupt_message_with_resume() -> None:
    msg = format_interrupt_message("agent run stopped", resume_cmd="opentorus run x --resume")
    assert "Interrupted" in msg
    assert "saved" in msg
    assert "Resume with: opentorus run x --resume" in msg


def test_run_keyboardinterrupt_is_graceful(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    # Force the agent loop to be interrupted mid-run.
    monkeypatch.setattr(
        AgentLoop, "run", lambda self, prompt: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    res = runner.invoke(app, ["run", "do something"])
    assert res.exit_code == 130
    assert "Interrupted" in res.stdout
    assert "--resume" in res.stdout
    # Run state is persisted so `--resume` works.
    assert (workspace_dir(tmp_path) / "run_state.json").is_file()
