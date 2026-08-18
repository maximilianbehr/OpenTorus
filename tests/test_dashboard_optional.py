"""The dashboard is optional: importing the CLI, the campaign package and the
dashboard package (adapters included) never imports ``textual``; without the extra,
``run_dashboard`` and ``campaign dashboard ID`` fail with the actionable message
(exit 1); the export flags keep working on a base install."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import opentorus
from opentorus.cli import app
from opentorus.dashboard import MISSING_TEXTUAL_MESSAGE, require_textual, run_dashboard
from opentorus.errors import OpenTorusError
from opentorus.paths import WORKSPACE_DIRNAME

runner = CliRunner()

_IMPORT_PROBE = (
    "import sys, opentorus.cli, opentorus.campaign, opentorus.dashboard, "
    "opentorus.dashboard.adapters; "
    "assert 'textual' not in sys.modules, sorted(m for m in sys.modules if 'textual' in m); "
    "print('ok')"
)


def test_core_imports_leave_textual_out_of_sys_modules() -> None:
    """Run in a subprocess so another test's ``import textual`` cannot mask a leak."""
    src_dir = Path(opentorus.__file__).resolve().parent.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src_dir) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ok"


def _init_campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["problem", "new", "For every n >= 1, P(n) holds."]).exit_code == 0
    res = runner.invoke(
        app, ["campaign", "start", "PROBLEM-0001", "--mode", "exploration", "--no-run"]
    )
    assert res.exit_code == 0, res.output
    return tmp_path / WORKSPACE_DIRNAME


def test_require_textual_and_run_dashboard_raise_actionable_error_without_the_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "textual", None)  # ``import textual`` -> ImportError
    with pytest.raises(OpenTorusError) as excinfo:
        require_textual()
    assert str(excinfo.value) == MISSING_TEXTUAL_MESSAGE
    assert "pip install 'opentorus[dashboard]'" in str(excinfo.value)
    ot = _init_campaign(tmp_path, monkeypatch)
    with pytest.raises(OpenTorusError, match="optional 'dashboard' extra"):
        run_dashboard(ot, "CAMPAIGN-0001")


def test_cli_dashboard_exits_1_with_the_message_without_textual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_campaign(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "textual", None)
    res = runner.invoke(app, ["campaign", "dashboard", "CAMPAIGN-0001"])
    assert res.exit_code == 1, res.output
    assert "opentorus[dashboard]" in " ".join(res.output.split())
    live = runner.invoke(app, ["campaign", "dashboard", "CAMPAIGN-0001", "--live"])
    assert live.exit_code == 1 and "opentorus[dashboard]" in " ".join(live.output.split())


def test_cli_dashboard_exports_work_without_textual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_campaign(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "textual", None)
    js = runner.invoke(app, ["campaign", "dashboard", "CAMPAIGN-0001", "--json"])
    assert js.exit_code == 0, js.output
    data = json.loads(js.output)
    assert data["campaign_id"] == "CAMPAIGN-0001" and "ROOT" in data["nodes"]
    # byte-identical to ``campaign tree --json``: the same graph, the same renderer
    tree = runner.invoke(app, ["campaign", "tree", "CAMPAIGN-0001", "--json"])
    assert tree.exit_code == 0 and tree.output == js.output
    plain = runner.invoke(app, ["campaign", "dashboard", "CAMPAIGN-0001", "--plain"])
    assert plain.exit_code == 0 and plain.output.startswith("Proof tree: PROBLEM-0001")
    assert "Problem status (derived from dossier artifacts):" in plain.output
    dot = runner.invoke(app, ["campaign", "dashboard", "CAMPAIGN-0001", "--dot"])
    assert dot.exit_code == 0 and dot.output.startswith("digraph proof_tree {")


def test_cli_dashboard_errors_and_help(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_campaign(tmp_path, monkeypatch)
    both = runner.invoke(app, ["campaign", "dashboard", "CAMPAIGN-0001", "--json", "--dot"])
    assert both.exit_code == 1 and "Choose one" in both.output
    missing = runner.invoke(app, ["campaign", "dashboard", "CAMPAIGN-0042", "--json"])
    assert missing.exit_code == 1 and "No campaign 'CAMPAIGN-0042'" in missing.output
    help_text = " ".join(runner.invoke(app, ["campaign", "dashboard", "--help"]).output.split())
    assert "read-only" in help_text and "opentorus[dashboard]" in help_text
    assert "same graph as `campaign tree`" in help_text
    assert "--live" in help_text and "--refresh" in help_text and "--json" in help_text
