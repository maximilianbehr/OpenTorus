"""Tests for the tool-environment registry (Milestone 56).

A registry entry resolves to a pinned image and default command; the manifest
records backend + image ref + environment; an unknown environment fails clearly;
a missing container runtime is reported as unavailable rather than crashing. All
offline (no real container).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opentorus.errors import OpenTorusError
from opentorus.execution import backends as backends_mod
from opentorus.execution.environments import (
    ENVIRONMENTS_FILENAME,
    list_environments,
    resolve_environment,
)
from opentorus.research.experiments import new_experiment, run_experiment
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _manifest(ot: Path, exp) -> dict:
    text = (ot / exp.path / "results" / "manifest.yaml").read_text()
    return yaml.safe_load(text)


def _seed_prepared_env(ot: Path, name: str, image: str = "opentorus-julia:local") -> None:
    (ot / ENVIRONMENTS_FILENAME).write_text(
        yaml.safe_dump(
            {
                "environments": {
                    name: {
                        "image": image,
                        "containerfile": "docker/Dockerfile",
                        "build_context": "docker",
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_builtin_environments_present(tmp_path: Path) -> None:
    envs = list_environments(_ot(tmp_path))
    for name in ("python-sci", "julia", "cpp", "macaulay2", "matlab", "mathematica"):
        assert name in envs
    assert envs["julia"].default_command == "julia run.jl"
    assert envs["julia"].image is None


def test_resolve_unknown_environment_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(OpenTorusError) as exc:
        resolve_environment(_ot(tmp_path), "nope")
    assert "Unknown tool environment" in str(exc.value)


def test_workspace_overrides_builtin(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    (ot / ENVIRONMENTS_FILENAME).write_text(
        yaml.safe_dump({"environments": {"julia": {"image": "opentorus-julia:local@sha256:abc"}}}),
        encoding="utf-8",
    )
    env = resolve_environment(ot, "julia")
    assert env.image == "opentorus-julia:local@sha256:abc"


def test_new_experiment_with_environment_sets_command(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "Julia run", environment="julia")
    assert exp.environment == "julia"
    assert exp.command == "julia run.jl"


def test_new_experiment_unknown_environment_rejected(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    with pytest.raises(OpenTorusError):
        new_experiment(ot, "x", environment="bogus")


def test_unprepared_environment_fails_at_run(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "Julia run", environment="julia")
    exp, code = run_experiment(ot, exp.id, timeout=20)
    assert code == 127
    assert exp.status == "failed"
    manifest = _manifest(ot, exp)
    assert manifest["backend"] == "unavailable"
    stderr = (ot / exp.path / "results" / "stderr.txt").read_text(encoding="utf-8")
    assert "env prepare" in stderr


def test_manifest_records_backend_and_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ot = _ot(tmp_path)
    _seed_prepared_env(ot, "julia")
    monkeypatch.setattr(backends_mod, "_which", lambda binary: binary == "docker")
    exp = new_experiment(ot, "Julia run", environment="julia")
    exp, _code = run_experiment(ot, exp.id, timeout=20)
    manifest = _manifest(ot, exp)
    assert manifest["backend"] == "docker"
    assert manifest["tool_environment"] == "julia"
    assert manifest["image_ref"] == "opentorus-julia:local"
    assert "tool_versions" in manifest


def test_environment_without_runtime_reported_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ot = _ot(tmp_path)
    _seed_prepared_env(ot, "julia")
    monkeypatch.setattr(backends_mod, "_which", lambda binary: False)
    exp = new_experiment(ot, "Julia run", environment="julia")
    exp, code = run_experiment(ot, exp.id, timeout=20)
    assert code == 127
    assert exp.status == "failed"
    manifest = _manifest(ot, exp)
    assert manifest["backend"] == "unavailable"
    assert manifest["image_ref"] == "opentorus-julia:local"


def test_plain_experiment_still_runs_locally(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "Plain", template="counterexample_search")
    exp, code = run_experiment(ot, exp.id, timeout=20)
    assert code == 0
    manifest = _manifest(ot, exp)
    assert manifest["backend"] == "local"
    assert manifest["tool_environment"] is None


def _seed_hashed_env(ot: Path, name: str, image: str, cf_hash: str) -> None:
    (ot / ENVIRONMENTS_FILENAME).write_text(
        yaml.safe_dump(
            {
                "environments": {
                    name: {
                        "image": image,
                        "containerfile": "docker/Dockerfile",
                        "build_context": "docker",
                        "containerfile_sha256": cf_hash,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_run_refuses_an_image_built_from_another_workspaces_containerfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Executing in someone else's environment must fail loudly, not silently.

    A locally built image is named by a mutable tag. In a parallel stress run a
    second workspace's ``env prepare`` replaced the tag, and experiments then ran
    in a container without their own dependencies — reported as ordinary
    ModuleNotFoundErrors, indistinguishable from the model writing bad code.
    """
    ot = _ot(tmp_path)
    _seed_hashed_env(ot, "julia", "opentorus-julia:aaaaaaaaaaaa", "a" * 64)
    monkeypatch.setattr(backends_mod, "_which", lambda binary: binary == "docker")
    # The tag now carries an image built from a different Containerfile.
    monkeypatch.setattr("opentorus.execution.prepare._image_label", lambda *_a, **_kw: "b" * 64)
    monkeypatch.setattr("opentorus.execution.prepare._image_exists", lambda *_a, **_kw: True)

    exp = new_experiment(ot, "Julia run", environment="julia")
    exp, code = run_experiment(ot, exp.id, timeout=20)

    assert code == 127
    assert exp.status == "failed"
    stderr = (ot / exp.path / "results" / "stderr.txt").read_text(encoding="utf-8")
    assert "different Containerfile" in stderr
    assert "Nothing was executed" in stderr
    manifest = _manifest(ot, exp)
    assert manifest["backend"] == "unavailable"


def test_run_proceeds_when_the_image_matches_the_recorded_containerfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ot = _ot(tmp_path)
    _seed_hashed_env(ot, "julia", "opentorus-julia:aaaaaaaaaaaa", "a" * 64)
    monkeypatch.setattr(backends_mod, "_which", lambda binary: binary == "docker")
    monkeypatch.setattr("opentorus.execution.prepare._image_label", lambda *_a, **_kw: "a" * 64)
    exp = new_experiment(ot, "Julia run", environment="julia")
    exp, _code = run_experiment(ot, exp.id, timeout=20)
    manifest = _manifest(ot, exp)
    assert manifest["backend"] == "docker"
