"""Offline checks on the packaging gate and the release pipeline.

The workflows cannot run here, but their shape can be pinned: the release
workflow must be tag-triggered, must publish nothing unless the repository
variable is set, must hand write permissions only to the two jobs that need
them, and must pin every third-party action to a commit. The packaging gate in
``lint.yml`` must install both the wheel and the sdist into clean venvs, and
the extras the docs advertise must exist in ``pyproject.toml``.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = _ROOT / ".github" / "workflows"
_RELEASE = _WORKFLOWS / "release.yml"
_LINT = _WORKFLOWS / "lint.yml"
_RELEASE_DOC = _ROOT / "docs" / "release.md"

# Every action step must name one of these forms: a first-party major tag or a
# full commit SHA. Third-party actions are held to the SHA form separately.
_MAJOR_TAG = re.compile(r"^actions/[a-z-]+@v\d+$")
_SHA_PIN = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def _uses(job: dict[str, Any]) -> list[str]:
    return [step["uses"] for step in job["steps"] if "uses" in step]


@pytest.fixture(scope="module")
def release() -> dict[str, Any]:
    return _load(_RELEASE)


@pytest.fixture(scope="module")
def lint() -> dict[str, Any]:
    return _load(_LINT)


# --- both workflows parse -----------------------------------------------------


@pytest.mark.parametrize("path", [_RELEASE, _LINT, _WORKFLOWS / "tests.yml"])
def test_workflow_parses_as_yaml(path: Path) -> None:
    data = _load(path)
    assert "jobs" in data and data["jobs"], path


# --- release.yml --------------------------------------------------------------


def test_release_triggers_on_version_tags(release: dict[str, Any]) -> None:
    # PyYAML reads the bare key `on` as boolean True (YAML 1.1); accept both.
    triggers = release.get("on", release.get(True))
    assert triggers == {"push": {"tags": ["v*"]}}


def test_release_default_permissions_are_read_only(release: dict[str, Any]) -> None:
    assert release["permissions"] == {"contents": "read"}


def test_release_has_expected_jobs_in_dependency_order(release: dict[str, Any]) -> None:
    jobs = release["jobs"]
    assert list(jobs) == [
        "test",
        "build",
        "install-smoke",
        "sbom",
        "provenance",
        "publish",
        "github-release",
    ]
    assert jobs["build"]["needs"] == "test"
    for name in ("install-smoke", "sbom", "provenance"):
        assert jobs[name]["needs"] == "build", name
    for name in ("publish", "github-release"):
        assert sorted(jobs[name]["needs"]) == ["install-smoke", "provenance", "sbom"], name


def test_publish_and_release_are_gated_by_repository_variable(release: dict[str, Any]) -> None:
    jobs = release["jobs"]
    gate = "vars.OPENTORUS_RELEASE_PUBLISH == 'true'"
    assert jobs["publish"]["if"] == gate
    assert jobs["github-release"]["if"] == gate
    # No other job carries a gate: the dry run must always run to completion.
    for name, job in jobs.items():
        if name not in {"publish", "github-release"}:
            assert "if" not in job, name


def test_publish_uses_trusted_publishing_without_a_password(release: dict[str, Any]) -> None:
    publish = release["jobs"]["publish"]
    assert publish["environment"]["name"] == "pypi"
    assert publish["permissions"] == {"id-token": "write"}
    steps = [s for s in publish["steps"] if "pypa/gh-action-pypi-publish" in s.get("uses", "")]
    assert len(steps) == 1
    with_ = steps[0].get("with", {})
    assert "password" not in with_
    assert "user" not in with_


def test_only_provenance_and_publish_hold_id_token_write(release: dict[str, Any]) -> None:
    holders = {
        name
        for name, job in release["jobs"].items()
        if job.get("permissions", {}).get("id-token") == "write"
    }
    assert holders == {"provenance", "publish"}
    assert release["jobs"]["provenance"]["permissions"] == {
        "id-token": "write",
        "attestations": "write",
        "contents": "read",
    }


def test_only_github_release_holds_contents_write(release: dict[str, Any]) -> None:
    holders = {
        name
        for name, job in release["jobs"].items()
        if job.get("permissions", {}).get("contents") == "write"
    }
    assert holders == {"github-release"}
    steps = [
        s
        for s in release["jobs"]["github-release"]["steps"]
        if "softprops/action-gh-release" in s.get("uses", "")
    ]
    assert len(steps) == 1
    assert steps[0]["with"]["draft"] is True


def test_third_party_actions_are_sha_pinned_with_version_comment(release: dict[str, Any]) -> None:
    text = _RELEASE.read_text(encoding="utf-8")
    third_party = []
    for job in release["jobs"].values():
        for ref in _uses(job):
            if _MAJOR_TAG.match(ref):
                continue
            third_party.append(ref)
            assert _SHA_PIN.match(ref), f"third-party action not SHA-pinned: {ref}"
            # The version comment sits on the same line as the pin.
            line = next(ln for ln in text.splitlines() if ref in ln)
            assert re.search(r"#\s*v\d+\.\d+\.\d+", line), line
    assert {ref.split("@")[0] for ref in third_party} == {
        "anchore/sbom-action",
        "pypa/gh-action-pypi-publish",
        "softprops/action-gh-release",
    }


def test_release_build_checks_tag_against_version_textually(release: dict[str, Any]) -> None:
    run = _run_text(release["jobs"]["build"])
    assert "src/opentorus/__init__.py" in run
    assert "GITHUB_REF_NAME" in run
    assert "__version__" in run
    # Textual, not `import opentorus`: the check must not depend on an install.
    assert "import opentorus" not in run
    assert "python -m build" in run
    assert "twine check dist/*" in run


def test_release_smoke_installs_wheel_and_sdist(release: dict[str, Any]) -> None:
    run = _run_text(release["jobs"]["install-smoke"])
    assert "pip install dist/*.whl" in run
    assert "pip install dist/*.tar.gz" in run
    assert "opentorus --version" in run
    assert "'textual' not in sys.modules" in run
    assert "[dashboard]" in run


def test_release_sbom_and_provenance_produce_artifacts(release: dict[str, Any]) -> None:
    sbom_steps = release["jobs"]["sbom"]["steps"]
    sbom = next(s for s in sbom_steps if "anchore/sbom-action" in s.get("uses", ""))
    assert sbom["with"]["output-file"] == "sbom.spdx.json"
    assert sbom["with"]["format"] == "spdx-json"
    prov = next(
        s
        for s in release["jobs"]["provenance"]["steps"]
        if s.get("uses", "").startswith("actions/attest-build-provenance@")
    )
    assert prov["with"]["subject-path"] == "dist/*"


def test_release_header_explains_the_publish_gate() -> None:
    head = "\n".join(_RELEASE.read_text(encoding="utf-8").splitlines()[:25])
    assert "OPENTORUS_RELEASE_PUBLISH" in head
    assert "trusted publisher" in head


# --- lint.yml build job -------------------------------------------------------


def test_lint_build_job_installs_wheel_and_sdist_into_clean_venvs(lint: dict[str, Any]) -> None:
    assert lint["permissions"] == {"contents": "read"}
    assert "concurrency" in lint
    assert list(lint["jobs"]) == ["ruff", "typecheck", "build"]
    build = lint["jobs"]["build"]
    names = [s.get("name", "") for s in build["steps"]]
    assert "Install wheel into a clean venv" in names
    assert "Install sdist into a second clean venv" in names
    assert "Import without optional deps" in names
    assert "Dashboard extra" in names
    run = _run_text(build)
    assert "pip install build twine" in run
    assert "python -m build" in run
    assert "twine check dist/*" in run
    assert "python -m venv .venv-wheel" in run
    assert "pip install dist/*.whl" in run
    assert "python -m venv .venv-sdist" in run
    assert "pip install dist/*.tar.gz" in run
    assert 'OT="$PWD/.venv-wheel/bin/opentorus"' in run
    assert '"$OT" init' in run
    assert '"$OT" doctor --json' in run
    assert "'textual' not in sys.modules" in run
    assert "[dashboard]" in run
    uploads = [u for u in _uses(build) if u.startswith("actions/upload-artifact@")]
    assert uploads == ["actions/upload-artifact@v4"]


def test_lint_build_bash_steps_declare_bash_shell(lint: dict[str, Any]) -> None:
    for step in lint["jobs"]["build"]["steps"]:
        run = step.get("run", "")
        if "\n" in run.strip():
            assert step.get("shell") == "bash", step.get("name")


# --- pyproject extras -----------------------------------------------------------


def test_pyproject_has_dashboard_extra_and_dev_tooling() -> None:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    assert any(req.startswith("textual") for req in extras["dashboard"])
    dev = extras["dev"]
    assert any(req.startswith("twine") for req in dev)
    assert any(req.startswith("textual") for req in dev)
    assert any(req.startswith("build") for req in dev)
    # textual must not have crept into the core dependencies.
    assert not any(req.startswith("textual") for req in data["project"]["dependencies"])


# --- docs -------------------------------------------------------------------------


def test_release_doc_exists_and_covers_the_essentials() -> None:
    assert _RELEASE_DOC.is_file()
    text = _RELEASE_DOC.read_text(encoding="utf-8")
    for needle in (
        "trusted publishing",
        "yank",
        "OPENTORUS_RELEASE_PUBLISH",
        "src/opentorus/__init__.py",
        "twine check dist/*",
        "opentorus[dashboard]",
        "Action pinning policy",
    ):
        assert needle in text, needle
    # Docs are ASCII only (repo convention: no Unicode diagrams or dashes).
    assert text.isascii()


def test_contributing_points_at_release_doc() -> None:
    text = (_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "docs/release.md" in text
