"""Tests for licensed (BYO) tools and container-as-sandbox (Milestone 57).

Default runs request no network and a read-only workspace with a writable results
mount; resource limits pass through; proprietary tools are bring-your-own and
never bundled; license material is sensitive (excluded from bundles). Offline.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.execution import DockerBackend, sandboxed_mounts
from opentorus.execution.base import ExecutionRequest, RunLimits
from opentorus.execution.environments import list_environments
from opentorus.permissions.policy import is_sensitive_path


def _req(tmp_path: Path, **kw) -> ExecutionRequest:
    base = {"command": "echo hi", "workdir": tmp_path, "image": "img"}
    base.update(kw)
    return ExecutionRequest(**base)


def test_sandboxed_mounts_workspace_readonly_results_writable(tmp_path: Path) -> None:
    mounts = sandboxed_mounts(tmp_path)
    work = next(m for m in mounts if m.target == "/work")
    results = next(m for m in mounts if m.target == "/work/results")
    assert work.read_only is True
    assert results.read_only is False


def test_docker_sandbox_argv_marks_readonly_workspace(tmp_path: Path) -> None:
    req = _req(tmp_path, mounts=sandboxed_mounts(tmp_path))
    argv = DockerBackend().build_argv(req)
    joined = " ".join(argv)
    assert f"{tmp_path}:/work:ro" in joined
    # The results mount is read-write (no :ro suffix).
    assert f"{tmp_path}/results:/work/results" in joined
    assert f"{tmp_path}/results:/work/results:ro" not in joined


def test_default_run_has_no_network(tmp_path: Path) -> None:
    argv = DockerBackend().build_argv(_req(tmp_path))
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"


def test_limits_pass_through(tmp_path: Path) -> None:
    req = _req(tmp_path, limits=RunLimits(timeout=5, memory="1g", cpus="1"))
    argv = DockerBackend().build_argv(req)
    assert argv[argv.index("--memory") + 1] == "1g"
    assert argv[argv.index("--cpus") + 1] == "1"


def test_proprietary_environments_are_bring_your_own(tmp_path: Path) -> None:
    envs = list_environments(tmp_path)
    for name in ("matlab", "mathematica"):
        env = envs[name]
        assert env.license == "proprietary"
        assert env.image is None
        assert env.is_bring_your_own is True


def test_open_environments_are_not_byo(tmp_path: Path) -> None:
    # OpenTorus no longer ships prebuilt images: open stacks have no image until
    # the user runs ``env prepare``, so an unprepared open stack is image-less
    # (nothing to pin). What separates them from proprietary tools is the open
    # license and that, once an image is built, they are ordinary non-BYO runtimes.
    env = list_environments(tmp_path)["julia"]
    assert env.license == "open"
    assert env.image is None
    prepared = env.model_copy(update={"image": "opentorus-julia@sha256:" + "0" * 64})
    assert prepared.is_bring_your_own is False


def test_license_material_is_sensitive() -> None:
    for name in ("network.lic", "license.dat", "mlm.dat", "matlab.mathpass", "foo.lic"):
        assert is_sensitive_path(name), name


def test_license_material_excluded_from_bundle(tmp_path: Path) -> None:
    from opentorus.agent.session import SessionMessage, append_message
    from opentorus.bundle import export_session, import_bundle
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    append_message(ot, SessionMessage(role="user", content="x", metadata={"session_id": "S1"}))
    # Plant a license file inside a bundled artifact dir (reports/).
    (ot / "reports").mkdir(parents=True, exist_ok=True)
    (ot / "reports" / "network.lic").write_text("SERVER licserver", encoding="utf-8")

    bundle = export_session(ot, "S1")
    dest = import_bundle(ot, bundle, dest=tmp_path / "review")
    assert not (dest / "artifacts" / "reports" / "network.lic").exists()
