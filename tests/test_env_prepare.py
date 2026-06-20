"""Tests for opentorus env prepare (local container setup)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opentorus.errors import OpenTorusError
from opentorus.execution.environments import ENVIRONMENTS_FILENAME, resolve_environment
from opentorus.execution.prepare import (
    local_image_tag,
    prepare_environment,
    resolve_build_paths,
)
from opentorus.workspace import init_workspace, workspace_dir


def _dockerfile(tmp_path: Path) -> Path:
    path = tmp_path / "docker" / "Dockerfile"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("FROM scratch\n", encoding="utf-8")
    return path


def test_local_image_tag() -> None:
    assert local_image_tag("python-sci") == "opentorus-python-sci:local"


def test_prepare_requires_dockerfile(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    with pytest.raises(OpenTorusError, match="--file"):
        prepare_environment(ot, "python-sci")


def test_prepare_writes_workspace_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    dockerfile = _dockerfile(tmp_path)

    monkeypatch.setattr(
        "opentorus.execution.prepare._pick_container_runtime",
        lambda _cfg: "docker",
    )
    monkeypatch.setattr(
        "opentorus.execution.prepare._image_exists",
        lambda _runtime, _tag: True,
    )
    build_calls: list[str] = []
    monkeypatch.setattr(
        "opentorus.execution.prepare._build_image",
        lambda runtime, tag, **kw: build_calls.append(f"{runtime}:{tag}"),
    )

    result = prepare_environment(ot, "python-sci", containerfile=dockerfile)
    assert result.built is False
    assert result.image == "opentorus-python-sci:local"
    assert not build_calls

    env = resolve_environment(ot, "python-sci")
    assert env.image == "opentorus-python-sci:local"

    data = yaml.safe_load((ot / ENVIRONMENTS_FILENAME).read_text(encoding="utf-8"))
    entry = data["environments"]["python-sci"]
    assert entry["image"] == "opentorus-python-sci:local"
    assert entry["containerfile"] == "docker/Dockerfile"


def test_prepare_builds_when_image_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    dockerfile = _dockerfile(tmp_path)

    monkeypatch.setattr(
        "opentorus.execution.prepare._pick_container_runtime",
        lambda _cfg: "docker",
    )
    monkeypatch.setattr(
        "opentorus.execution.prepare._image_exists",
        lambda _runtime, _tag: False,
    )
    monkeypatch.setattr(
        "opentorus.execution.prepare._build_image",
        lambda runtime, tag, **kw: None,
    )

    result = prepare_environment(ot, "python-sci", containerfile=dockerfile)
    assert result.built is True


def test_prepare_custom_dockerfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    dockerfile = _dockerfile(tmp_path)

    monkeypatch.setattr(
        "opentorus.execution.prepare._pick_container_runtime",
        lambda _cfg: "docker",
    )
    monkeypatch.setattr(
        "opentorus.execution.prepare._image_exists",
        lambda _runtime, _tag: True,
    )
    built: list[tuple[Path, Path]] = []

    def _record_build(runtime: str, tag: str, **kw) -> None:
        built.append((kw["context"], kw["containerfile"]))

    monkeypatch.setattr("opentorus.execution.prepare._build_image", _record_build)

    result = prepare_environment(ot, "python-sci", containerfile=dockerfile)
    assert result.containerfile == dockerfile.resolve()
    assert result.build_context == dockerfile.parent.resolve()

    data = yaml.safe_load((ot / ENVIRONMENTS_FILENAME).read_text(encoding="utf-8"))
    entry = data["environments"]["python-sci"]
    assert entry["containerfile"] == "docker/Dockerfile"
    assert entry["build_context"] == "docker"


def test_prepare_reuses_saved_custom_dockerfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    dockerfile = _dockerfile(tmp_path)

    monkeypatch.setattr(
        "opentorus.execution.prepare._pick_container_runtime",
        lambda _cfg: "docker",
    )
    monkeypatch.setattr(
        "opentorus.execution.prepare._image_exists",
        lambda _runtime, _tag: True,
    )
    monkeypatch.setattr(
        "opentorus.execution.prepare._build_image",
        lambda runtime, tag, **kw: None,
    )

    prepare_environment(ot, "python-sci", containerfile=dockerfile)
    ctx, cf = resolve_build_paths(ot, "python-sci")
    assert cf == dockerfile.resolve()
    assert ctx == dockerfile.parent.resolve()


def test_prepare_custom_env_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    dockerfile = tmp_path / "MyDockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")

    monkeypatch.setattr(
        "opentorus.execution.prepare._pick_container_runtime",
        lambda _cfg: "docker",
    )
    monkeypatch.setattr(
        "opentorus.execution.prepare._image_exists",
        lambda _runtime, _tag: True,
    )
    monkeypatch.setattr(
        "opentorus.execution.prepare._build_image",
        lambda runtime, tag, **kw: None,
    )

    result = prepare_environment(
        ot,
        "my-nystrom",
        containerfile=dockerfile,
        default_command="python scripts/run.py",
    )
    assert result.image == "opentorus-my-nystrom:local"
    env = resolve_environment(ot, "my-nystrom")
    assert env.default_command == "python scripts/run.py"


def test_prepare_fails_without_container_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    dockerfile = _dockerfile(tmp_path)

    def _no_runtime(_cfg: object) -> str:
        raise OpenTorusError("No container runtime found.")

    monkeypatch.setattr(
        "opentorus.execution.prepare._pick_container_runtime",
        _no_runtime,
    )
    with pytest.raises(OpenTorusError, match="No container runtime"):
        prepare_environment(ot, "python-sci", containerfile=dockerfile)
