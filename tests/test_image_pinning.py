"""Tests for pinned images & the build/publish pipeline (Milestone 64).

An unpinned environment is flagged; a pinned ref round-trips into the registry
and the manifest; the SIF/OCI digest is recorded. Offline via fixtures — no real
build or registry pull.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from opentorus.errors import OpenTorusError
from opentorus.execution import backends as backends_mod
from opentorus.execution.environments import ENVIRONMENTS_FILENAME, resolve_environment
from opentorus.execution.pinning import (
    image_digest,
    is_digest_pinned,
    pin_environment,
    resolve_and_pin,
    sif_cache_path,
    unpinned_environments,
    verify_pinned,
)
from opentorus.research.experiments import new_experiment, run_experiment
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _fake_digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def _seed_env(ot: Path, name: str, image: str) -> None:
    (ot / ENVIRONMENTS_FILENAME).write_text(
        yaml.safe_dump({"environments": {name: {"image": image}}}),
        encoding="utf-8",
    )


def test_unpinned_environment_is_flagged(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    _seed_env(ot, "julia", "opentorus-julia:local")
    unpinned = {e.name for e in unpinned_environments(ot)}
    assert "julia" in unpinned
    assert "matlab" not in unpinned
    with pytest.raises(OpenTorusError):
        verify_pinned(ot)


def test_is_digest_pinned_recognizes_digests() -> None:
    assert is_digest_pinned("opentorus-julia:local@" + _fake_digest("j"))
    assert not is_digest_pinned("opentorus-julia:local")
    assert not is_digest_pinned(None)


def test_pin_round_trips_into_registry(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    _seed_env(ot, "julia", "opentorus-julia:local")
    digest = _fake_digest("julia")
    pin_environment(ot, "julia", digest)
    env = resolve_environment(ot, "julia")
    assert is_digest_pinned(env.image)
    assert image_digest(env.image) == digest


def test_resolve_and_pin_pins_prepared_environments(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    (ot / ENVIRONMENTS_FILENAME).write_text(
        yaml.safe_dump(
            {
                "environments": {
                    "julia": {"image": "opentorus-julia:local"},
                    "python-sci": {"image": "opentorus-python-sci:local"},
                }
            }
        ),
        encoding="utf-8",
    )
    written = resolve_and_pin(ot, lambda env: _fake_digest(env.name))
    assert "julia" in written and "python-sci" in written
    assert "matlab" not in written
    verify_pinned(ot)


def test_pin_bring_your_own_fails(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    with pytest.raises(OpenTorusError):
        pin_environment(ot, "matlab", _fake_digest("m"))


def test_pinned_image_digest_recorded_in_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ot = _ot(tmp_path)
    _seed_env(ot, "julia", "opentorus-julia:local")
    digest = _fake_digest("julia")
    pin_environment(ot, "julia", digest)
    monkeypatch.setattr(backends_mod, "_which", lambda binary: binary == "docker")
    exp = new_experiment(ot, "pinned julia", environment="julia")
    exp, _code = run_experiment(ot, exp.id, timeout=20)
    manifest = yaml.safe_load((ot / exp.path / "results" / "manifest.yaml").read_text())
    assert manifest["image_digest"] == digest
    assert digest in (manifest["image_ref"] or "")


def test_apptainer_records_sif_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opentorus.config import CONFIG_FILENAME, default_config, write_config

    ot = _ot(tmp_path)
    _seed_env(ot, "julia", "opentorus-julia:local")
    digest = _fake_digest("julia")
    pin_environment(ot, "julia", digest)
    monkeypatch.setattr(backends_mod, "_which", lambda binary: binary == "apptainer")
    config = default_config()
    config.execution.backend = "apptainer"
    write_config(ot / CONFIG_FILENAME, config)
    exp = new_experiment(ot, "apptainer julia", environment="julia")
    exp, _code = run_experiment(ot, exp.id, timeout=20)
    manifest = yaml.safe_load((ot / exp.path / "results" / "manifest.yaml").read_text())
    assert manifest["backend"] == "apptainer"
    assert manifest["sif_cache"] == str(sif_cache_path(digest))
