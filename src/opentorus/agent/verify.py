"""Edit verification and bounded self-repair.

Core principle: never claim success without validation. After the agent edits the
workspace, we run the configured quality gates. If they fail, we attempt a bounded
self-repair loop — feed the failing output back to the agent, let it propose a
fix, and re-check — capped to a few attempts. If gates still fail, we report
"validation failed" honestly rather than pretending success.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.agent.loop import AgentLoop
from opentorus.config import Config
from opentorus.quality import CheckResult, run_checks

DEFAULT_MAX_REPAIR_ATTEMPTS = 2

VerificationStatus = Literal["not_needed", "passed", "repaired", "failed"]


class VerificationOutcome(BaseModel):
    status: VerificationStatus
    attempts: int = 0
    detail: str = ""
    checks: list[CheckResult] = Field(default_factory=list)


def _all_ok(checks: list[CheckResult]) -> bool:
    return all(c.ok or c.skipped for c in checks)


def _failing(checks: list[CheckResult]) -> list[CheckResult]:
    return [c for c in checks if not c.ok and not c.skipped]


def _repair_prompt(checks: list[CheckResult]) -> str:
    lines = [
        "Quality-gate repair (this turn only). Fix ONLY the failing gate output below "
        "with the smallest apply_patch or write_file change, then stop.",
        "Do NOT call exp_new, exp_run, status, claim_new, memory_add, or re-read scripts "
        "unless a gate error names that file.",
        "Do NOT re-run experiments or start pending tasks from status.",
        "Failing gates:",
    ]
    for check in _failing(checks):
        lines.append(f"\n## {check.name} (exit {check.exit_code}): {check.command}")
        if check.stdout_summary:
            lines.append(f"stdout:\n{check.stdout_summary}")
        if check.stderr_summary:
            lines.append(f"stderr:\n{check.stderr_summary}")
    return "\n".join(lines)


def verify_and_repair(
    loop: AgentLoop,
    root: Path,
    ot_dir: Path,
    config: Config,
    *,
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
) -> VerificationOutcome:
    """Run quality gates after edits and attempt a bounded self-repair on failure."""
    if not loop.edited:
        return VerificationOutcome(status="not_needed", detail="No edits to verify.")

    edited_paths = [path for path, _, _ in loop._pending_edits]
    checks = run_checks(root, ot_dir, config, edited_paths=edited_paths or None)
    if _all_ok(checks):
        return VerificationOutcome(status="passed", detail="Quality gates passed.", checks=checks)

    saved_task_id = loop._task_id
    try:
        loop._task_id = None  # repair is not a planned task — avoid mixed prompts
        for attempt in range(1, max_repair_attempts + 1):
            loop.run(_repair_prompt(checks))
            checks = run_checks(root, ot_dir, config, edited_paths=edited_paths or None)
            if _all_ok(checks):
                return VerificationOutcome(
                    status="repaired",
                    attempts=attempt,
                    detail=f"Quality gates passed after {attempt} repair attempt(s).",
                    checks=checks,
                )
    finally:
        loop._task_id = saved_task_id

    failing = ", ".join(c.name for c in _failing(checks))
    return VerificationOutcome(
        status="failed",
        attempts=max_repair_attempts,
        detail=f"Validation failed after {max_repair_attempts} repair attempt(s): {failing}.",
        checks=checks,
    )
