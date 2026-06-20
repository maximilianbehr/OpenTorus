"""Tests for reproducibility replay (Milestone 41)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.experiments import new_experiment, run_experiment
from opentorus.research.repro import replay_experiment
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_deterministic_experiment_replays(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    exp = new_experiment(ot, "deterministic run")
    run_experiment(ot, exp.id)
    report = replay_experiment(ot, exp.id)
    assert report.reproducible
    assert report.stdout_matches
    assert report.recorded_seed == report.replay_seed == 42
    assert report.divergences == []


def test_replay_without_manifest_raises(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    exp = new_experiment(ot, "never run")
    with pytest.raises(OpenTorusError):
        replay_experiment(ot, exp.id)


def test_changed_behavior_is_reported(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    exp = new_experiment(ot, "will change")
    run_experiment(ot, exp.id)

    # Change the experiment so its output diverges from the recorded run.
    run_py = ot / exp.path / "run.py"
    run_py.write_text(
        'import json\nprint(json.dumps({"seed": 7, "metric": 0.5}))\n',
        encoding="utf-8",
    )
    report = replay_experiment(ot, exp.id)
    assert not report.reproducible
    assert not report.stdout_matches
    assert report.stdout_diff
    assert report.replay_seed == 7
    assert any("seed changed" in d for d in report.divergences)


def test_replay_does_not_overwrite_recorded_results(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    exp = new_experiment(ot, "preserve baseline")
    run_experiment(ot, exp.id)
    recorded = (ot / exp.path / "results" / "stdout.txt").read_text(encoding="utf-8")

    run_py = ot / exp.path / "run.py"
    run_py.write_text('print("totally different")\n', encoding="utf-8")
    replay_experiment(ot, exp.id)

    # The recorded baseline stdout is unchanged by the replay.
    assert (ot / exp.path / "results" / "stdout.txt").read_text(encoding="utf-8") == recorded


def test_replay_report_is_written(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    exp = new_experiment(ot, "writes report")
    run_experiment(ot, exp.id)
    replay_experiment(ot, exp.id)
    replays = ot / exp.path / "results" / "replays"
    assert replays.is_dir()
    assert list(replays.glob("*.yaml"))
