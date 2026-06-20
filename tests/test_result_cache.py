"""Tests for the content-addressed result cache (Milestone 66).

A repeated run hits the cache; changing the seed/image invalidates the key.
Offline (local backend).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from opentorus.execution.cache import cache_key
from opentorus.research.experiments import new_experiment, run_experiment
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _manifest(ot: Path, exp) -> dict:
    return yaml.safe_load((ot / exp.path / "results" / "manifest.yaml").read_text())


def test_repeated_run_hits_cache(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "cached", template="counterexample_search")
    exp, _ = run_experiment(ot, exp.id, timeout=30)
    assert _manifest(ot, exp)["cache_hit"] is False
    # Re-run the same experiment: identical content ⇒ cache hit.
    exp, _ = run_experiment(ot, exp.id, timeout=30)
    manifest = _manifest(ot, exp)
    assert manifest["cache_hit"] is True
    assert manifest["cache_key"]


def test_changing_source_invalidates_cache(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "v1", template="counterexample_search")
    run_experiment(ot, exp.id, timeout=30)
    # A second experiment with different source content gets a different key.
    body = "import json\nprint(json.dumps({'seed': 1, 'metric': 2.0}))\n"
    exp2 = new_experiment(ot, "v2", run_body=body)
    exp2, _ = run_experiment(ot, exp2.id, timeout=30)
    assert _manifest(ot, exp2)["cache_hit"] is False


def test_cache_key_changes_with_seed_and_image() -> None:
    base = cache_key(run_source="SEED=1\n", image_ref=None, command="python run.py")
    seed = cache_key(run_source="SEED=2\n", image_ref=None, command="python run.py")
    image = cache_key(run_source="SEED=1\n", image_ref="img@sha256:abc", command="python run.py")
    assert base != seed
    assert base != image
