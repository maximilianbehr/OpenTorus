"""The experiment result cache keys on the content the run actually depends on.

A command like ``python scripts/foo.py`` references a workspace script; rewriting
that script must invalidate the cache — the old result must never be replayed as
if the new script produced it. And a genuine cache hit must preserve the original
run's start/end timing instead of claiming the replay moment as the execution
time. Offline (local backend).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from opentorus.execution.cache import cache_key
from opentorus.research.experiments import (
    Experiment,
    _cache_key_for,
    new_experiment,
    run_experiment,
)
from opentorus.workspace import init_workspace, workspace_dir

_SCRIPT_V1 = "print('marker-v1')\n"
_SCRIPT_V2 = "print('marker-v2')\n"


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _manifest(ot: Path, exp: Experiment) -> dict:
    return yaml.safe_load((ot / exp.path / "results" / "manifest.yaml").read_text())


def _stdout(ot: Path, exp: Experiment) -> str:
    return (ot / exp.path / "results" / "stdout.txt").read_text()


def _workspace_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "scripts" / "foo.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    return script


def test_rewriting_a_referenced_script_invalidates_the_cache(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    script = _workspace_script(tmp_path, _SCRIPT_V1)
    exp = new_experiment(ot, "script run", command="python scripts/foo.py")

    exp, code = run_experiment(ot, exp.id, timeout=30)
    assert code == 0
    assert _manifest(ot, exp)["cache_hit"] is False
    assert "marker-v1" in _stdout(ot, exp)

    # Identical content (including the referenced script) ⇒ cache hit.
    exp, _ = run_experiment(ot, exp.id, timeout=30)
    assert _manifest(ot, exp)["cache_hit"] is True

    # Rewriting the referenced script changes the run's identity: the cache must
    # NOT serve the old result as if the new script had produced it.
    script.write_text(_SCRIPT_V2, encoding="utf-8")
    exp, code = run_experiment(ot, exp.id, timeout=30)
    assert code == 0
    assert _manifest(ot, exp)["cache_hit"] is False
    assert "marker-v2" in _stdout(ot, exp)
    assert "marker-v1" not in _stdout(ot, exp)


def test_cache_key_folds_referenced_script_content(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    script = _workspace_script(tmp_path, _SCRIPT_V1)
    exp = new_experiment(ot, "script run", command="python scripts/foo.py")
    exp_dir = ot / exp.path

    key_v1 = _cache_key_for(ot, exp, exp_dir)
    assert _cache_key_for(ot, exp, exp_dir) == key_v1  # deterministic
    script.write_text(_SCRIPT_V2, encoding="utf-8")
    assert _cache_key_for(ot, exp, exp_dir) != key_v1


def test_key_unchanged_when_command_references_no_workspace_files(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "plain")  # default: `python run.py`, run from the exp dir
    exp_dir = ot / exp.path
    run_source = (exp_dir / "run.py").read_text(encoding="utf-8")
    # run.py is already hashed as run_source; with no other referenced files the
    # key stays byte-identical to the pre-existing scheme (stability guarantee).
    assert _cache_key_for(ot, exp, exp_dir) == cache_key(
        run_source=run_source, image_ref=None, command="python run.py"
    )


def test_cache_hit_preserves_original_run_timing(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    _workspace_script(tmp_path, _SCRIPT_V1)
    exp = new_experiment(ot, "timing", command="python scripts/foo.py")

    exp, _ = run_experiment(ot, exp.id, timeout=30)
    original = _manifest(ot, exp)
    assert original["cache_hit"] is False
    assert original["replayed_at"] is None

    exp, _ = run_experiment(ot, exp.id, timeout=30)
    replayed = _manifest(ot, exp)
    assert replayed["cache_hit"] is True
    # The manifest keeps the ORIGINAL run's start/end — a replay never claims the
    # current moment as the run's execution time.
    assert replayed["start_time"] == original["start_time"]
    assert replayed["end_time"] == original["end_time"]
    # The replay moment lives in a separate field.
    assert replayed["replayed_at"] is not None
    assert replayed["replayed_at"] >= replayed["end_time"]
