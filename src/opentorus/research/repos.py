"""External code as inspectable evidence (Milestone 72).

A ``REPO-*`` artifact pins a public repository at an exact commit (egress-gated)
and records its URL, commit, and license. The clone lives inside the workspace
and its test suite can be executed in a *sandboxed* execution environment
(Phase 18); the outcome is recorded as **observed** evidence linked to a claim —
never as a verification of the claim itself. Repository credentials and any
fetched secrets are sensitive (M20/M44) and are never bundled.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field

from opentorus.config import Config
from opentorus.errors import OpenTorusError
from opentorus.jsonl import next_sequential_id
from opentorus.tools.shell import ShellResult, run_argv

if TYPE_CHECKING:
    from opentorus.research.egress import EgressGuard

# A cloner performs ``clone url @ commit -> dest``; it raises on failure.
CloneFn = Callable[[str, str, Path], None]
# A test runner executes the repo's suite in ``clone_dir`` and returns the result.
TestRunner = Callable[["Repo", Path], ShellResult]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Repo(BaseModel):
    id: str
    url: str
    commit: str
    name: str
    license: str | None = None
    clone_path: str | None = None
    cloned: bool = False
    test_command: str | None = None
    access_note: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


def repos_dir(ot_dir: Path) -> Path:
    return ot_dir / "repos"


def _meta_path(repo_dir: Path) -> Path:
    return repo_dir / "metadata.yaml"


def list_repos(ot_dir: Path) -> list[Repo]:
    base = repos_dir(ot_dir)
    if not base.is_dir():
        return []
    out: list[Repo] = []
    for child in sorted(base.iterdir()):
        meta = _meta_path(child)
        if child.is_dir() and meta.is_file():
            data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
            out.append(Repo.model_validate(data))
    return out


def get_repo(ot_dir: Path, repo_id: str) -> Repo | None:
    for repo in list_repos(ot_dir):
        if repo.id == repo_id:
            return repo
    return None


def _save_meta(ot_dir: Path, repo: Repo) -> None:
    repo_dir = repos_dir(ot_dir) / repo.id
    repo_dir.mkdir(parents=True, exist_ok=True)
    _meta_path(repo_dir).write_text(
        yaml.safe_dump(repo.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )


def _repo_name(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail[:-4] if tail.endswith(".git") else tail


# Best-effort SPDX-ish license detection from the conventional license file.
_LICENSE_MARKERS: tuple[tuple[str, str], ...] = (
    ("Apache License", "Apache-2.0"),
    ("MIT License", "MIT"),
    ("Permission is hereby granted, free of charge", "MIT"),
    ("BSD 3-Clause", "BSD-3-Clause"),
    ("BSD 2-Clause", "BSD-2-Clause"),
    ("Redistribution and use in source and binary forms", "BSD"),
    ("GNU GENERAL PUBLIC LICENSE", "GPL"),
    ("GNU LESSER GENERAL PUBLIC LICENSE", "LGPL"),
    ("Mozilla Public License", "MPL-2.0"),
)


def detect_license(clone_dir: Path) -> str | None:
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "LICENCE"):
        path = clone_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for marker, spdx in _LICENSE_MARKERS:
                if marker.lower() in text.lower():
                    return spdx
            return "unknown (license file present)"
    return None


def _default_cloner(clone_command: str) -> CloneFn:
    def _clone(url: str, commit: str, dest: Path) -> None:
        git = shlex.split(clone_command)
        clone = run_argv([*git, "clone", "--quiet", "--", url, str(dest)], timeout=300)
        if clone.exit_code != 0:
            raise OpenTorusError(f"git clone failed: {clone.stderr.strip()[:300]}")
        checkout = run_argv([*git, "-C", str(dest), "checkout", "--quiet", commit], timeout=120)
        if checkout.exit_code != 0:
            raise OpenTorusError(f"git checkout {commit} failed: {checkout.stderr.strip()[:300]}")

    return _clone


def clone_repo(
    ot_dir: Path,
    url: str,
    commit: str,
    *,
    config: Config,
    cloner: CloneFn | None = None,
    egress: EgressGuard | None = None,
) -> Repo:
    """Clone a public repository at a *pinned commit* into a ``REPO-*`` artifact.

    The commit must be specified (no moving ``HEAD``) so the evidence is
    reproducible. Egress is authorized for the repository host before fetching.
    """
    if not commit:
        raise OpenTorusError("A pinned commit (full SHA or tag) is required for reproducibility.")
    if egress is not None:
        egress.authorize(url)

    repo_id = next_sequential_id("REPO", len(list_repos(ot_dir)))
    repo_dir = repos_dir(ot_dir) / repo_id
    clone_dir = repo_dir / "clone"
    repo_dir.mkdir(parents=True, exist_ok=True)

    do_clone = cloner or _default_cloner(config.tools.code_evidence.clone_command)
    do_clone(url, commit, clone_dir)

    repo = Repo(
        id=repo_id,
        url=url,
        commit=commit,
        name=_repo_name(url),
        cloned=clone_dir.is_dir(),
        clone_path=str(clone_dir.relative_to(ot_dir)) if clone_dir.is_dir() else None,
        license=detect_license(clone_dir) if clone_dir.is_dir() else None,
        access_note=f"cloned at pinned commit {commit}",
    )
    _save_meta(ot_dir, repo)
    return repo


def _backend_test_runner(ot_dir: Path, config: Config, command: str) -> TestRunner:
    def _run(repo: Repo, clone_dir: Path) -> ShellResult:
        from opentorus.execution import (
            ExecutionRequest,
            RunLimits,
            sandboxed_mounts,
            select_backend,
        )

        (clone_dir / "results").mkdir(parents=True, exist_ok=True)
        backend = select_backend(config, needs_image=False)
        request = ExecutionRequest(
            command=command,
            workdir=clone_dir,
            mounts=sandboxed_mounts(clone_dir),
            network=config.execution.network,
            limits=RunLimits(timeout=600),
        )
        return backend.run(request)

    return _run


def run_repo_tests(
    ot_dir: Path,
    repo_id: str,
    *,
    config: Config,
    claim_id: str | None = None,
    test_command: str = "python -m pytest -q",
    runner: TestRunner | None = None,
) -> tuple[Repo, ShellResult]:
    """Run a repo's test suite in a sandbox and record the outcome as evidence.

    The result is **observed**, not a verification: evidence is recorded with a
    neutral direction and an explicit limitation, and (when a claim is given) a
    ``REPO tests CLAIM`` edge is added.
    """
    repo = get_repo(ot_dir, repo_id)
    if repo is None:
        raise OpenTorusError(f"No repo with id '{repo_id}'.")
    if not repo.clone_path:
        raise OpenTorusError(f"Repo '{repo_id}' has no local clone to run tests in.")

    clone_dir = ot_dir / repo.clone_path
    run = runner or _backend_test_runner(ot_dir, config, test_command)
    result = run(repo, clone_dir)

    results_dir = repos_dir(ot_dir) / repo_id / "test-results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (results_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")

    repo.test_command = test_command
    _save_meta(ot_dir, repo)

    if claim_id is not None:
        from opentorus.research.dossier.store import get_active_problem
        from opentorus.research.evidence import add_evidence
        from opentorus.research.graph import add_edge

        outcome = "passed" if result.exit_code == 0 else f"failed (exit {result.exit_code})"
        add_evidence(
            ot_dir,
            claim_id,
            source_type="code",
            source_id=repo_id,
            summary=(
                f"Ran {repo.name}'s test suite ({test_command}) at commit "
                f"{repo.commit[:12]}: tests {outcome}."
            ),
            direction="neutral",
            strength="weak",
            limitations=[
                "Observed result of running the authors' own tests; "
                "this is not a verification of the claim itself.",
            ],
            problem_id=get_active_problem(ot_dir),
        )
        add_edge(
            ot_dir,
            repo_id,
            claim_id,
            "tests",
            rationale=f"repo test suite executed as observed evidence (tests {outcome}).",
        )

    return repo, result
