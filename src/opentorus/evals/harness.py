"""Eval cases, graders, and the run harness.

Each :class:`EvalCase` is a task plus a lightweight grader expressed as keyword
and tool-use expectations. A run executes every case against the deterministic
mock provider inside an isolated temporary workspace (so the user's real
``.opentorus/`` is never touched), grades the outcome, and writes a manifest.
"""

from __future__ import annotations

import platform
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    name: str
    goal: str
    # Substrings the final answer must contain (case-insensitive).
    must_contain: list[str] = Field(default_factory=list)
    # A tool that must have been used during the run (None = no requirement).
    must_use_tool: str | None = None


class EvalResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""
    answer: str = ""
    tools_used: list[str] = Field(default_factory=list)


class EvalRun(BaseModel):
    suite: str
    seed: int
    started_at: datetime
    finished_at: datetime
    total: int
    passed: int
    results: list[EvalResult]
    environment: dict = Field(default_factory=dict)
    manifest_path: str | None = None

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total


def _capture_environment() -> dict:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "provider": "mock",
    }


def _grade(case: EvalCase, answer: str, tools_used: list[str]) -> EvalResult:
    haystack = answer.lower()
    missing = [kw for kw in case.must_contain if kw.lower() not in haystack]
    tool_ok = case.must_use_tool is None or case.must_use_tool in tools_used
    passed = not missing and tool_ok
    details: list[str] = []
    if missing:
        details.append(f"missing keywords: {', '.join(missing)}")
    if not tool_ok:
        details.append(f"expected tool '{case.must_use_tool}' was not used")
    return EvalResult(
        name=case.name,
        passed=passed,
        detail="; ".join(details) or "ok",
        answer=answer,
        tools_used=tools_used,
    )


def _run_case(case: EvalCase) -> EvalResult:
    from opentorus.actions import list_actions
    from opentorus.agent.loop import AgentLoop
    from opentorus.config import default_config
    from opentorus.providers.mock_provider import MockProvider
    from opentorus.tools.builtin import build_default_registry
    from opentorus.workspace import init_workspace, workspace_dir

    with tempfile.TemporaryDirectory(prefix="opentorus-eval-") as tmp:
        root = Path(tmp)
        init_workspace(root)
        ot = workspace_dir(root)
        registry = build_default_registry(root, ot)
        loop = AgentLoop(root, ot, MockProvider(), registry, default_config())
        answer = loop.run(case.goal)
        tools_used = [entry.tool_name for entry in list_actions(ot)]
    return _grade(case, answer, tools_used)


def run_suite(ot_dir: Path, suite: str, seed: int = 0) -> EvalRun:
    """Run every case in ``suite`` and write a manifest under ``.opentorus/evals/``."""
    from opentorus.evals.suites import get_suite

    cases = get_suite(suite)
    started = datetime.now(UTC)
    results = [_run_case(case) for case in cases]
    finished = datetime.now(UTC)

    run = EvalRun(
        suite=suite,
        seed=seed,
        started_at=started,
        finished_at=finished,
        total=len(results),
        passed=sum(1 for r in results if r.passed),
        results=results,
        environment=_capture_environment(),
    )
    run.manifest_path = str(_write_manifest(ot_dir, run))
    return run


def _write_manifest(ot_dir: Path, run: EvalRun) -> Path:
    run_id = run.started_at.strftime("%Y%m%dT%H%M%S")
    out_dir = ot_dir / "evals" / run.suite / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.yaml"
    data = run.model_dump(mode="json")
    data.pop("manifest_path", None)
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return manifest
