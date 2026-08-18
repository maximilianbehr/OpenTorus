"""``opentorus campaign`` through the CliRunner (offline mock path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.paths import WORKSPACE_DIRNAME

runner = CliRunner()


def _flat(text: str) -> str:
    """Collapse Rich wrapping/panel borders so phrases can be matched across lines."""
    return " ".join(text.replace("│", " ").split())


def _init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    res = runner.invoke(app, ["problem", "new", "For every n >= 1, P(n) holds."])
    assert res.exit_code == 0
    return tmp_path / WORKSPACE_DIRNAME


def test_start_prints_campaign_id_first_and_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ot = _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["campaign", "start", "PROBLEM-0001", "--mode", "exploration"])
    assert res.exit_code == 0, res.output
    assert res.output.splitlines()[0].strip() == "CAMPAIGN-0001"
    assert "campaign status: completed" in res.output
    assert "problem status" in res.output
    cdir = ot / "problems" / "PROBLEM-0001" / "campaigns" / "CAMPAIGN-0001"
    assert (cdir / "events.jsonl").is_file()
    assert (cdir / "snapshot.json").is_file()


def test_prove_or_refute_start_creates_primary_claim_and_prints_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    res = runner.invoke(
        app,
        [
            "campaign",
            "start",
            "PROBLEM-0001",
            "--mode",
            "prove-or-refute",
            "--branches",
            "4",
            "--max-steps",
            "40",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "CLAIM-0001" in res.output
    assert "designated it the primary claim" in res.output
    verdict = runner.invoke(app, ["problem", "verdict", "PROBLEM-0001"])
    assert verdict.exit_code == 0
    assert "CLAIM-0001" in verdict.output


@pytest.mark.parametrize(
    "args",
    [
        ["--mode", "bogus"],
        ["--mode", "prove-or-refute", "--branches", "1"],
        ["--max-steps", "-3"],
        ["--max-steps", "0"],
        ["--cost-budget", "-1"],
        ["--mode", "prove-or-refute", "--branches", "2", "--no-primary-claim"],
    ],
)
def test_invalid_start_requests_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["campaign", "start", "PROBLEM-0001", *args])
    assert res.exit_code == 2, res.output


def test_no_primary_claim_refusal_names_the_remediation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    res = runner.invoke(
        app,
        [
            "campaign",
            "start",
            "PROBLEM-0001",
            "--mode",
            "prove-or-refute",
            "--branches",
            "2",
            "--no-primary-claim",
        ],
    )
    assert res.exit_code == 2
    assert "problem claim PROBLEM-0001" in res.output
    assert "--set-primary" in res.output


def test_unknown_problem_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["campaign", "start", "PROBLEM-0009", "--mode", "exploration"])
    assert res.exit_code == 1
    assert "No problem dossier" in res.output


def test_status_json_has_root_math_status_and_both_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    assert (
        runner.invoke(app, ["campaign", "start", "PROBLEM-0001", "--mode", "exploration"]).exit_code
        == 0
    )
    res = runner.invoke(app, ["campaign", "status", "CAMPAIGN-0001", "--json"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["campaign_id"] == "CAMPAIGN-0001"
    assert data["status"] == "completed"
    assert data["phase"] == "completed"
    assert "root_math_status" in data
    assert data["root_math_status"]["report_status"] == "UNSOLVED"
    assert data["root_math_status"]["label"] in ("STATUS_UNCERTAIN", "INCONCLUSIVE")
    assert data["branch_counts"] == {"completed": 1}
    plain = runner.invoke(app, ["campaign", "status", "CAMPAIGN-0001"])
    assert plain.exit_code == 0
    flat = _flat(plain.output)
    assert "campaign status: completed" in flat
    assert "problem status (derived from dossier artifacts" in flat
    assert "does not mean the problem is solved" in flat


def test_help_texts_distinguish_campaign_and_problem_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = runner.invoke(app, ["campaign", "--help"])
    assert res.exit_code == 0
    text = _flat(res.output)
    assert "orchestration" in text
    assert "problem verdict" in text
    assert "does not mean the problem is solved" in text
    for cmd in ("list", "pause", "resume", "start", "status", "stop", "verify"):
        assert cmd in res.output
    start_help = runner.invoke(app, ["campaign", "start", "--help"])
    assert start_help.exit_code == 0
    assert "--no-primary-claim" in start_help.output and "--no-run" in start_help.output


def test_pause_resume_stop_list_verify_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    res = runner.invoke(
        app, ["campaign", "start", "PROBLEM-0001", "--mode", "exploration", "--no-run"]
    )
    assert res.exit_code == 0, res.output
    assert res.output.splitlines()[0].strip() == "CAMPAIGN-0001"
    res = runner.invoke(app, ["campaign", "pause", "CAMPAIGN-0001", "--reason", "lunch"])
    assert res.exit_code == 0, res.output
    assert "paused" in res.output and "lunch" in res.output
    status = json.loads(
        runner.invoke(app, ["campaign", "status", "CAMPAIGN-0001", "--json"]).output
    )
    assert status["status"] == "paused" and status["pause_reason"] == "lunch"
    assert status["resume_phase"] == "created"
    res = runner.invoke(app, ["campaign", "resume", "CAMPAIGN-0001"])
    assert res.exit_code == 0, res.output
    assert "resumed CAMPAIGN-0001" in res.output
    status = json.loads(
        runner.invoke(app, ["campaign", "status", "CAMPAIGN-0001", "--json"]).output
    )
    assert status["status"] == "completed"
    # idempotent resume on a completed campaign
    res = runner.invoke(app, ["campaign", "resume", "CAMPAIGN-0001"])
    assert res.exit_code == 0 and "already completed" in res.output
    # a second campaign, stopped
    res = runner.invoke(app, ["campaign", "start", "PROBLEM-0001", "--mode", "survey", "--no-run"])
    assert res.exit_code == 0 and "CAMPAIGN-0002" in res.output
    res = runner.invoke(app, ["campaign", "stop", "CAMPAIGN-0002"])
    assert res.exit_code != 0  # --reason is required
    res = runner.invoke(app, ["campaign", "stop", "CAMPAIGN-0002", "--reason", "enough"])
    assert res.exit_code == 0 and "stopped: enough" in res.output
    res = runner.invoke(app, ["campaign", "resume", "CAMPAIGN-0002"])
    assert res.exit_code == 0 and "already stopped" in res.output
    res = runner.invoke(app, ["campaign", "pause", "CAMPAIGN-0002", "--reason", "x"])
    assert res.exit_code == 1
    listing = runner.invoke(app, ["campaign", "list"])
    assert listing.exit_code == 0
    assert "CAMPAIGN-0001" in listing.output and "CAMPAIGN-0002" in listing.output
    listing_json = json.loads(runner.invoke(app, ["campaign", "list", "--json"]).output)
    assert [row["campaign_id"] for row in listing_json] == ["CAMPAIGN-0001", "CAMPAIGN-0002"]
    assert listing_json[1]["status"] == "stopped"
    only = json.loads(
        runner.invoke(app, ["campaign", "list", "--problem", "PROBLEM-0001", "--json"]).output
    )
    assert len(only) == 2
    verify = runner.invoke(app, ["campaign", "verify", "CAMPAIGN-0001"])
    assert verify.exit_code == 0, verify.output
    assert "replay matches snapshot" in verify.output
    verify_json = json.loads(
        runner.invoke(app, ["campaign", "verify", "CAMPAIGN-0001", "--json"]).output
    )
    assert verify_json["matches"] is True


def test_verify_exits_1_on_replay_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ot = _init(tmp_path, monkeypatch)
    assert (
        runner.invoke(app, ["campaign", "start", "PROBLEM-0001", "--mode", "exploration"]).exit_code
        == 0
    )
    snapshot = ot / "problems" / "PROBLEM-0001" / "campaigns" / "CAMPAIGN-0001" / "snapshot.json"
    data = json.loads(snapshot.read_text())
    data["rounds"] = 99
    snapshot.write_text(json.dumps(data))
    res = runner.invoke(app, ["campaign", "verify", "CAMPAIGN-0001"])
    assert res.exit_code == 1
    assert "MISMATCH" in res.output and "rounds" in res.output


def test_unknown_campaign_id_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(tmp_path, monkeypatch)
    for cmd in (
        ["status"],
        ["resume"],
        ["verify"],
        ["pause", "--reason", "x"],
        ["stop", "--reason", "x"],
    ):
        res = runner.invoke(app, ["campaign", *cmd[:1], "CAMPAIGN-0007", *cmd[1:]])
        assert res.exit_code == 1, (cmd, res.output)
        assert "No campaign" in res.output


def test_list_without_campaigns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["campaign", "list"])
    assert res.exit_code == 0
    assert "No campaigns yet" in res.output


def test_interrupt_exits_130_with_a_resume_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, monkeypatch)
    from opentorus.campaign.engine import CampaignEngine

    def _interrupt(self, problem_id: str, **kwargs: object) -> None:  # noqa: ANN001
        raise KeyboardInterrupt

    monkeypatch.setattr(CampaignEngine, "start", _interrupt)
    res = runner.invoke(app, ["campaign", "start", "PROBLEM-0001", "--mode", "exploration"])
    assert res.exit_code == 130
    assert "paused" in res.output and "campaign resume" in res.output
