"""Offline tests for code-as-evidence (Milestone 72).

Cloning and test execution are stubbed (no network, no containers). A pinned
``REPO-*`` artifact records URL+commit+license; a stubbed test run is recorded as
observed evidence with provenance; the cloned working tree is excluded from
session bundles.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from opentorus.bundle import export_session
from opentorus.config import default_config
from opentorus.research.evidence import list_evidence
from opentorus.research.graph import list_edges
from opentorus.research.repos import (
    clone_repo,
    detect_license,
    get_repo,
    run_repo_tests,
)
from opentorus.tools.shell import ShellResult


def _ot(tmp_path):  # noqa: ANN001
    ot = tmp_path / ".opentorus"
    ot.mkdir()
    return ot


def _fake_cloner(license_text: str = "MIT License\n\nPermission is hereby granted"):
    def _clone(url: str, commit: str, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "LICENSE").write_text(license_text, encoding="utf-8")
        (dest / "test_thing.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    return _clone


def test_clone_repo_pins_url_commit_license(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    repo = clone_repo(
        ot,
        "https://github.com/acme/torus.git",
        "a" * 40,
        config=config,
        cloner=_fake_cloner(),
    )
    assert repo.id == "REPO-0001"
    assert repo.url == "https://github.com/acme/torus.git"
    assert repo.commit == "a" * 40
    assert repo.name == "torus"
    assert repo.license == "MIT"
    assert repo.cloned is True
    assert get_repo(ot, repo.id) is not None


def test_clone_requires_pinned_commit(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    with pytest.raises(Exception):  # noqa: B017,PT011 - missing commit is rejected
        clone_repo(ot, "https://x/y.git", "", config=default_config(), cloner=_fake_cloner())


def test_detect_license_apache(tmp_path) -> None:  # noqa: ANN001
    clone = tmp_path / "c"
    clone.mkdir()
    (clone / "LICENSE").write_text("Apache License\nVersion 2.0", encoding="utf-8")
    assert detect_license(clone) == "Apache-2.0"


def test_run_repo_tests_records_observed_evidence(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    repo = clone_repo(
        ot, "https://github.com/acme/torus.git", "b" * 40, config=config, cloner=_fake_cloner()
    )

    def _runner(r, clone_dir):  # noqa: ANN001, ANN202
        return ShellResult(command="pytest", stdout="1 passed", stderr="", exit_code=0)

    # A claim to attach the observed result to.
    from opentorus.research.claims import new_claim

    claim = new_claim(ot, "Their method converges.")

    _, result = run_repo_tests(ot, repo.id, config=config, claim_id=claim.id, runner=_runner)
    assert result.exit_code == 0

    evidence = list_evidence(ot, claim.id)
    assert len(evidence) == 1
    ev = evidence[0]
    assert ev.source_type == "code"
    assert ev.source_id == repo.id
    assert ev.direction == "neutral"  # observed, never a verification
    assert any("not a verification" in lim for lim in ev.limitations)

    edges = [e for e in list_edges(ot) if e.source_id == repo.id and e.target_id == claim.id]
    assert edges and edges[0].relation == "tests"

    # The outcome is captured under the repo's test-results.
    assert (ot / "repos" / repo.id / "test-results" / "stdout.txt").read_text() == "1 passed"


def test_clone_excluded_from_bundle(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    repo = clone_repo(
        ot, "https://github.com/acme/torus.git", "c" * 40, config=config, cloner=_fake_cloner()
    )
    # A secret accidentally present in the clone must never be bundled.
    (ot / repo.clone_path / "secret.env").write_text("TOKEN=abc123", encoding="utf-8")

    from opentorus.agent.session import SessionMessage, append_message

    append_message(ot, SessionMessage(role="user", content="hello", metadata={"session_id": "s1"}))
    out = export_session(ot, "s1", out_path=ot / "b.zip")

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    # Metadata is shareable; the cloned tree (and its secret) is not.
    assert any(n.endswith(f"repos/{repo.id}/metadata.yaml") for n in names)
    assert not any("clone" in n for n in names)
    assert not any("secret.env" in n for n in names)
