"""Tests for opentorus env prepare (local container setup)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
import yaml

from opentorus.errors import OpenTorusError
from opentorus.execution.environments import (
    ENVIRONMENTS_FILENAME,
    ToolEnvironment,
    resolve_environment,
)
from opentorus.execution.prepare import (
    CONTAINERFILE_LABEL,
    containerfile_sha256,
    environment_image_mismatch,
    local_image_tag,
    prepare_environment,
    resolve_build_paths,
)
from opentorus.tools.shell import ShellResult
from opentorus.workspace import init_workspace, workspace_dir


def _dockerfile(tmp_path: Path) -> Path:
    path = tmp_path / "docker" / "Dockerfile"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("FROM scratch\n", encoding="utf-8")
    return path


def _stub_matching_label(monkeypatch: pytest.MonkeyPatch, dockerfile: Path) -> None:
    """Make the existing image carry the current Containerfile's hash label."""
    monkeypatch.setattr(
        "opentorus.execution.prepare._image_label",
        lambda _runtime, _tag, _label: containerfile_sha256(dockerfile),
    )


def test_local_image_tag() -> None:
    assert local_image_tag("python-sci") == "opentorus-python-sci:local"


def test_local_image_tag_is_content_addressed() -> None:
    """Different build inputs must never resolve to the same tag.

    Every shipped example names its environment ``python-sci``; with one tag per
    name, a second workspace's prepare replaced the first workspace's image.
    """
    one = local_image_tag("python-sci", "a" * 64)
    two = local_image_tag("python-sci", "b" * 64)
    assert one == "opentorus-python-sci:" + "a" * 12
    assert one != two
    # Identical Containerfiles still share an image — dedup, not collision.
    assert local_image_tag("python-sci", "a" * 64) == one


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
    _stub_matching_label(monkeypatch, dockerfile)
    build_calls: list[str] = []
    monkeypatch.setattr(
        "opentorus.execution.prepare._build_image",
        lambda runtime, tag, **kw: build_calls.append(f"{runtime}:{tag}"),
    )

    cf_hash = containerfile_sha256(dockerfile)
    expected_tag = f"opentorus-python-sci:{cf_hash[:12]}"

    result = prepare_environment(ot, "python-sci", containerfile=dockerfile)
    assert result.built is False
    assert result.image == expected_tag
    assert not build_calls

    env = resolve_environment(ot, "python-sci")
    assert env.image == expected_tag
    assert env.containerfile_sha256 == cf_hash

    data = yaml.safe_load((ot / ENVIRONMENTS_FILENAME).read_text(encoding="utf-8"))
    entry = data["environments"]["python-sci"]
    assert entry["image"] == expected_tag
    assert entry["containerfile"] == "docker/Dockerfile"
    # The recorded hash is what lets a later run prove the tag still holds this
    # workspace's image.
    assert entry["containerfile_sha256"] == cf_hash


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
    _stub_matching_label(monkeypatch, dockerfile)
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
    _stub_matching_label(monkeypatch, dockerfile)
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
    _stub_matching_label(monkeypatch, dockerfile)
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
    assert result.image == f"opentorus-my-nystrom:{containerfile_sha256(dockerfile)[:12]}"
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


def test_two_workspaces_with_different_dockerfiles_get_different_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two workspaces preparing 'python-sci' must not end up sharing one image.

    All 66 shipped examples name their environment ``python-sci``. With a single
    ``opentorus-python-sci:local`` tag per machine, the second workspace's
    ``env prepare`` overwrote the image the first was pinned to, and the first
    one's experiments then ran against the other workspace's dependency set
    while its own ``environments.yaml`` still named its own Dockerfile.
    """
    monkeypatch.setattr(
        "opentorus.execution.prepare._pick_container_runtime", lambda _cfg: "docker"
    )
    monkeypatch.setattr("opentorus.execution.prepare._image_exists", lambda _runtime, _tag: False)
    monkeypatch.setattr("opentorus.execution.prepare._build_image", lambda runtime, tag, **kw: None)

    images = []
    for name, content in (
        ("wsA", "FROM scratch\nRUN echo A\n"),
        ("wsB", "FROM scratch\nRUN echo B\n"),
    ):
        root = tmp_path / name
        root.mkdir()
        init_workspace(root)
        dockerfile = root / "docker" / "Dockerfile"
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text(content, encoding="utf-8")
        result = prepare_environment(workspace_dir(root), "python-sci", containerfile=dockerfile)
        images.append(result.image)

    assert images[0] != images[1]


def test_environment_image_mismatch_detects_a_replaced_image() -> None:
    """A tag holding someone else's image is a refusal, not a silent wrong run."""
    env = ToolEnvironment(
        name="python-sci",
        image="opentorus-python-sci:abc123abc123",
        containerfile_sha256="a" * 64,
    )
    with (
        mock.patch("opentorus.execution.prepare._image_label", return_value="b" * 64),
        mock.patch("opentorus.execution.prepare._image_exists", return_value=True),
    ):
        problem = environment_image_mismatch(env, runtime="docker")
    assert problem is not None
    assert "different Containerfile" in problem
    assert "Nothing was executed" in problem


def test_environment_image_mismatch_accepts_the_matching_image() -> None:
    env = ToolEnvironment(
        name="python-sci",
        image="opentorus-python-sci:abc123abc123",
        containerfile_sha256="a" * 64,
    )
    with mock.patch("opentorus.execution.prepare._image_label", return_value="a" * 64):
        assert environment_image_mismatch(env, runtime="docker") is None


def test_environment_image_mismatch_is_silent_without_a_recorded_hash() -> None:
    """Environments prepared before the hash was recorded keep working unchanged."""
    env = ToolEnvironment(name="python-sci", image="opentorus-python-sci:local")
    assert environment_image_mismatch(env, runtime="docker") is None


def test_image_check_survives_a_tag_that_only_inspect_cannot_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``image inspect <tag>`` is not a reliable existence test.

    After eight concurrent builds wrote the same tag, a stress run left a daemon
    on which ``docker run`` and ``docker images -q`` both resolved the tag while
    ``docker image inspect <tag>`` answered "No such image". Checking by tag
    alone turned six runnable experiments into refusals — worse than the wrong
    environment the check exists to prevent.
    """
    tag = "opentorus-python-sci:82c91d6bef7d"
    image_id = "60fc84ea3e06"
    label_value = "a" * 64

    def fake_run_argv(argv, **_kw):
        if argv[1:3] == ["images", "-q"]:
            return ShellResult(command=" ".join(argv), stdout=image_id, stderr="", exit_code=0)
        if argv[1:3] == ["image", "inspect"]:
            if argv[3] == image_id:
                payload = json.dumps([{"Config": {"Labels": {CONTAINERFILE_LABEL: label_value}}}])
                return ShellResult(command=" ".join(argv), stdout=payload, stderr="", exit_code=0)
            return ShellResult(
                command=" ".join(argv), stdout="[]", stderr="No such image", exit_code=1
            )
        raise AssertionError(f"unexpected argv {argv}")

    monkeypatch.setattr("opentorus.execution.prepare.run_argv", fake_run_argv)
    env = ToolEnvironment(name="python-sci", image=tag, containerfile_sha256=label_value)
    assert environment_image_mismatch(env, runtime="docker") is None
