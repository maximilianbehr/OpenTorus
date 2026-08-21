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


def _seed_locally_built(ot: Path, name: str = "python-sci") -> None:
    (ot / ENVIRONMENTS_FILENAME).write_text(
        yaml.safe_dump(
            {
                "environments": {
                    name: {
                        "image": f"opentorus-{name}:a0173492e081",
                        "containerfile": "docker/Dockerfile",
                        "build_context": "docker",
                        "containerfile_sha256": "a0173492e081" + "0" * 52,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_locally_built_environments_are_not_reported_unpinned(tmp_path: Path) -> None:
    """`env verify` could never pass on a workspace the shipped examples produce.

    A local build has no registry digest — `RepoDigests` is empty — so every
    `env prepare`d environment was flagged, with advice that cannot be followed.
    It carries the Containerfile hash instead, which is checked against the image's
    build-time label before every run.
    """
    ot = _ot(tmp_path)
    _seed_locally_built(ot)
    assert unpinned_environments(ot) == []
    verify_pinned(ot)  # must not raise


def test_pinning_a_local_image_is_refused_rather_than_breaking_the_workspace(
    tmp_path: Path,
) -> None:
    """Following the old advice wrote a reference docker could only try to *pull*.

    `env pin` accepted a local image id, wrote `repo:tag@sha256:<id>` into
    environments.yaml, and every later experiment failed with "pull access denied".
    """
    ot = _ot(tmp_path)
    _seed_locally_built(ot)
    with pytest.raises(OpenTorusError, match="no registry digest"):
        pin_environment(ot, "python-sci", "sha256:" + "0" * 64)
