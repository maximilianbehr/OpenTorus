"""Quality gates: run the configured test/lint/typecheck commands.

Commands come from ``config.quality`` and are executed via the M4 shell runner.
Each run is summarized and logged as an action. Unconfigured gates are reported
as skipped rather than failing, so a partial setup still works.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from opentorus.actions import log_action
from opentorus.config import Config
from opentorus.tools.shell import run_shell

GATE_TIMEOUT = 600


class CheckResult(BaseModel):
    name: str
    command: str
    exit_code: int
    ok: bool
    skipped: bool = False
    stdout_summary: str | None = None
    stderr_summary: str | None = None


def _summarize(text: str, limit: int = 800) -> str | None:
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


_SKIP_DIRS = {".opentorus", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules"}


def workspace_has_quality_targets(root: Path) -> bool:
    """True when the workspace looks like a Python/code project worth gating."""
    if (root / "pyproject.toml").is_file() or (root / "setup.py").is_file():
        return True
    if (root / "tests").is_dir() or (root / "src").is_dir():
        return True
    for path in root.rglob("*.py"):
        if not any(part in _SKIP_DIRS for part in path.parts):
            return True
    return False


def _discoverable_tests(root: Path) -> bool:
    tests_dir = root / "tests"
    if tests_dir.is_dir() and any(tests_dir.rglob("test_*.py")):
        return True
    return any(p.is_file() and p.name.startswith("test_") for p in root.iterdir())


def _gate_command(
    root: Path,
    name: str,
    command: str,
    *,
    edited_paths: list[str] | None,
) -> tuple[str | None, str | None]:
    """Return (command, skip_reason). ``command`` is None when the gate should be skipped."""
    py_edited = [p for p in (edited_paths or []) if p.endswith(".py")]
    scoped = edited_paths is not None

    if name == "test":
        if scoped and not py_edited:
            return None, "skipped (no Python files edited)"
        if command.strip().startswith("pytest") and not _discoverable_tests(root):
            return None, "skipped (no tests/ directory or test_*.py files)"
        return command, None

    if name == "lint":
        if scoped and not py_edited:
            return None, "skipped (no Python files edited)"
        if scoped and py_edited:
            return f"ruff check {' '.join(py_edited)}", None
        return command, None

    if name == "typecheck":
        if scoped and not py_edited:
            return None, "skipped (no Python files edited)"
        if scoped and py_edited:
            return f"mypy {' '.join(py_edited)}", None
        return command, None

    return command, None


def run_checks(
    root: Path,
    ot_dir: Path,
    config: Config,
    only: list[str] | None = None,
    timeout: int = GATE_TIMEOUT,
    edited_paths: list[str] | None = None,
) -> list[CheckResult]:
    """Run the configured quality gates and return one result per gate."""
    if not workspace_has_quality_targets(root):
        return [
            CheckResult(
                name=name,
                command=command or "",
                exit_code=0,
                ok=True,
                skipped=True,
                stdout_summary="skipped (no Python project in workspace)",
            )
            for name, command in [
                ("test", config.quality.test_command),
                ("lint", config.quality.lint_command),
                ("typecheck", config.quality.typecheck_command),
            ]
        ]

    gates = [
        ("test", config.quality.test_command),
        ("lint", config.quality.lint_command),
        ("typecheck", config.quality.typecheck_command),
    ]
    results: list[CheckResult] = []
    for name, command in gates:
        if only and name not in only:
            continue
        if not command:
            results.append(CheckResult(name=name, command="", exit_code=0, ok=True, skipped=True))
            continue
        resolved, skip_reason = _gate_command(root, name, command, edited_paths=edited_paths)
        if resolved is None:
            results.append(
                CheckResult(
                    name=name,
                    command=command,
                    exit_code=0,
                    ok=True,
                    skipped=True,
                    stdout_summary=skip_reason,
                )
            )
            continue
        shell_result = run_shell(resolved, cwd=root, timeout=timeout)
        result = CheckResult(
            name=name,
            command=resolved,
            exit_code=shell_result.exit_code,
            ok=shell_result.exit_code == 0,
            stdout_summary=_summarize(shell_result.stdout),
            stderr_summary=_summarize(shell_result.stderr),
        )
        log_action(
            ot_dir,
            "check",
            ok=result.ok,
            args={"gate": name, "command": command},
            stdout_summary=result.stdout_summary,
            stderr_summary=result.stderr_summary,
        )
        results.append(result)
    return results
