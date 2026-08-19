"""Compatibility smoke: the pre-campaign CLI surface still runs end to end under the
mock provider — ``run``, ``research``, ``prove``, ``review``, ``problem report``,
``replay``, ``doctor`` — with the campaign layer present and (by default) silent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.paths import WORKSPACE_DIRNAME

runner = CliRunner()


def _init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    res = runner.invoke(app, ["problem", "new", "For every n >= 1, P(n) holds."])
    assert res.exit_code == 0, res.output
    return tmp_path / WORKSPACE_DIRNAME


def test_run_and_replay_under_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ot = _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["run", "show status"])
    assert res.exit_code == 0, res.output
    assert (ot / "session.jsonl").is_file()
    last = runner.invoke(app, ["replay", "last"])
    assert last.exit_code == 0, last.output
    assert not (ot / "problems" / "PROBLEM-0001" / "campaigns").exists()


def test_research_under_mock_records_no_campaign_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ot = _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["research", "Is P bounded?", "-n", "1"])
    assert res.exit_code == 0, res.output
    assert "1 iteration(s) this run" in res.output
    assert (ot / "research" / "is-p-bounded.json").is_file()
    assert not (ot / "problems" / "PROBLEM-0001" / "campaigns").exists()
    # opt-in: --campaign records an exploration campaign under the active problem
    res = runner.invoke(app, ["research", "Is P bounded?", "-n", "2", "--campaign"])
    assert res.exit_code == 0, res.output
    listing = runner.invoke(app, ["campaign", "list", "--json"])
    rows = json.loads(listing.output)
    assert len(rows) == 1 and rows[0]["problem_id"] == "PROBLEM-0001"
    assert rows[0]["mode"] == "exploration" and rows[0]["status"] == "completed"
    # --no-campaign wins over a config that opts in
    assert runner.invoke(app, ["config", "set", "campaign.record_research", "true"]).exit_code == 0
    res = runner.invoke(app, ["research", "Is P bounded?", "-n", "3", "--no-campaign"])
    assert res.exit_code == 0, res.output
    assert len(json.loads(runner.invoke(app, ["campaign", "list", "--json"]).output)) == 1


def test_prove_review_report_under_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ot = _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["prove", "PROBLEM-0001", "--no-literature"])
    assert res.exit_code in (0, 2), res.output  # 2 = honest gating verdict (gaps remain)
    proofs = ot / "problems" / "PROBLEM-0001" / "proof_attempts" / "index.jsonl"
    assert proofs.is_file() and proofs.read_text().strip()
    report = runner.invoke(app, ["problem", "report", "PROBLEM-0001"])
    assert report.exit_code == 0, report.output
    assert (ot / "problems" / "PROBLEM-0001" / "report.md").is_file()
    claim = runner.invoke(app, ["claim", "new", "P(n) holds for all n"])
    assert claim.exit_code == 0, claim.output
    review = runner.invoke(app, ["review", "run", "CLAIM-0001"])
    assert review.exit_code == 0, review.output
    assert (ot / "reviews" / "index.jsonl").is_file()
    assert not (ot / "problems" / "PROBLEM-0001" / "campaigns").exists()


def test_doctor_under_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code == 0, res.output
    as_json = runner.invoke(app, ["doctor", "--json"])
    assert as_json.exit_code == 0, as_json.output
    data = json.loads(as_json.output)
    checks = data if isinstance(data, list) else data.get("checks", data)
    assert checks
