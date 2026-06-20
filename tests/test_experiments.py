"""Tests for the experiment registry (Milestone 7)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from opentorus.actions import list_actions
from opentorus.config import CONFIG_FILENAME, default_config, write_config
from opentorus.errors import OpenTorusError
from opentorus.research.claims import get_claim, new_claim, update_claim
from opentorus.research.experiments import (
    EVIDENCE_NOTE,
    find_experiment_by_command,
    list_experiments,
    new_experiment,
    run_experiment,
    summarize_experiment,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_new_experiment_creates_folder(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    exp = new_experiment(base, "My experiment")
    assert exp.id == "EXP-0001"
    exp_dir = base / exp.path
    assert (exp_dir / "run.py").is_file()
    assert (exp_dir / "results").is_dir()
    assert (exp_dir / "config.yaml").is_file()
    summary = (exp_dir / "summary.md").read_text(encoding="utf-8")
    assert EVIDENCE_NOTE in summary


def test_ids_sequential(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_experiment(base, "a")
    exp2 = new_experiment(base, "b")
    assert exp2.id == "EXP-0002"
    assert len(list_experiments(base)) == 2


def test_run_experiment_captures_logs_and_completes(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_experiment(base, "runnable")
    exp, exit_code = run_experiment(base, "EXP-0001")
    assert exit_code == 0
    assert exp.status == "completed"
    stdout = (base / exp.path / "results" / "stdout.txt").read_text(encoding="utf-8")
    assert "metric" in stdout  # the template prints a JSON result
    assert list_actions(base)[-1].tool_name == "run_experiment"


def test_run_unknown_experiment_raises(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        run_experiment(base, "EXP-9999")


def test_summarize_experiment_after_run(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_experiment(base, "runnable")
    run_experiment(base, "EXP-0001")
    exp = summarize_experiment(base, "EXP-0001")
    summary = (base / exp.path / "summary.md").read_text(encoding="utf-8")
    assert "## Observed behavior" in summary
    assert "## Limitations" in summary
    assert "stdout" in summary
    assert EVIDENCE_NOTE in summary  # evidence-vs-truth distinction preserved


def test_summarize_unknown_experiment_raises(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        summarize_experiment(base, "EXP-9999")


def test_run_produces_manifest_with_command_and_environment(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_experiment(base, "runnable")
    exp, _ = run_experiment(base, "EXP-0001")
    manifest_path = base / exp.path / "results" / "manifest.yaml"
    assert manifest_path.is_file()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["experiment_id"] == "EXP-0001"
    assert "run.py" in manifest["command"]
    assert manifest["exit_code"] == 0
    assert manifest["status"] == "completed"
    assert manifest["stdout_path"] == "results/stdout.txt"
    assert "stdout.txt" in manifest["result_files"]
    assert manifest["environment"]["python_version"]  # capture_os_info default on
    assert manifest["random_seed"] == 42  # template uses a fixed seed


def test_manifest_respects_environment_flags(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    config = default_config()
    config.environment.capture_os_info = False
    config.environment.capture_git_state = False
    write_config(base / CONFIG_FILENAME, config)
    new_experiment(base, "runnable")
    exp, _ = run_experiment(base, "EXP-0001")
    manifest = yaml.safe_load(
        (base / exp.path / "results" / "manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["environment"] == {}
    assert manifest["git_commit"] is None
    assert manifest["dirty_git_state"] is None


def test_new_experiment_rejects_dangerous_command(tmp_path: Path) -> None:
    # exp_run executes a stored command outside the loop's permission gate, so a
    # dangerous command must be refused at the single execution choke point.
    base = _ws(tmp_path)
    with pytest.raises(OpenTorusError, match="dangerous"):
        new_experiment(base, "danger", command="rm -rf /")
    assert list_experiments(base) == []


def test_new_experiment_rejects_host_package_install(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    with pytest.raises(OpenTorusError, match="packages on the host"):
        new_experiment(base, "install", command="pip install numpy")


def test_run_experiment_blocked_in_review_mode(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_experiment(base, "runnable")  # benign default template
    config = default_config()
    config.agent.mode = "review"
    write_config(base / CONFIG_FILENAME, config)
    with pytest.raises(OpenTorusError, match="[Rr]eview mode"):
        run_experiment(base, "EXP-0001")


def test_summary_cites_manifest(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_experiment(base, "runnable")
    run_experiment(base, "EXP-0001")
    exp = summarize_experiment(base, "EXP-0001")
    summary = (base / exp.path / "summary.md").read_text(encoding="utf-8")
    assert "## Reproducibility" in summary
    assert "results/manifest.yaml" in summary


def test_claim_can_reference_experiment_support(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_experiment(base, "runnable")
    claim = new_claim(base, "Caching reduces latency")
    update_claim(base, claim.id, add_support="EXP-0001")
    refreshed = get_claim(base, claim.id)
    assert refreshed is not None
    assert "EXP-0001" in refreshed.support


def test_new_experiment_workspace_command(tmp_path: Path) -> None:
    root = tmp_path
    init_workspace(root)
    base = workspace_dir(root)
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "probe.py").write_text('print("workspace-run")\n', encoding="utf-8")
    exp = new_experiment(
        base,
        "External script",
        command=f"{sys.executable} scripts/probe.py",
    )
    assert exp.run_from == "workspace"
    assert "scripts/probe.py" in (exp.command or "")
    exp2, code = run_experiment(base, exp.id)
    assert code == 0
    stdout = (base / exp2.path / "results" / "stdout.txt").read_text(encoding="utf-8")
    assert "workspace-run" in stdout


def test_find_experiment_by_command(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    cmd = "python scripts/foo.py --all"
    created = new_experiment(base, "first", command=cmd)
    found = find_experiment_by_command(base, cmd)
    assert found is not None
    assert found.id == created.id
    assert find_experiment_by_command(base, "python other.py") is None
