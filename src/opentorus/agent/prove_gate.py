"""Tool guards for the prove-loop proof phase."""

from __future__ import annotations

import re
from collections.abc import Callable

from opentorus.permissions.policy import is_package_install_command

_PROVE_SHELL_BLOCKED = re.compile(
    r"\b(?:opentorus|python\s+-m\s+opentorus)\b",
    re.I,
)

_PROVE_RUN_SHELL_BLOCK = (
    "Blocked: run_shell is not available during prove. "
    "Run experiments via exp_new(title=..., command='python scripts/….py', "
    "environment='python-sci', run_from='workspace') then exp_run(exp_id=...). "
    "Prepare the image first: opentorus env prepare python-sci --file docker/Dockerfile. "
    "Use read_file / write_file for files."
)

# A path inside some dossier's directory, e.g. ".opentorus/problems/PROBLEM-0002/…".
_DOSSIER_PATH = re.compile(r"problems/(PROBLEM-\d+)", re.IGNORECASE)


def prove_tool_gate(
    pid: str,
    *,
    deliverable_done: Callable[[], bool],
) -> Callable[[str, dict], str | None]:
    """Guard the prove proof phase: pin dossier writes to the target problem and
    block CLI re-entry / package installs.

    A model (especially smaller local ones) can drift to a *different* dossier when
    several exist, writing the proof to the wrong problem and leaving the requested
    one empty. Any tool call that carries a ``problem_id`` must target this session's
    problem; otherwise it is rejected with a correction so the proof lands where the
    user asked.
    """
    target = pid.strip().upper()

    def gate(name: str, args: dict) -> str | None:
        from opentorus.research.dossier.store import canonical_problem_id

        raw = args.get("problem_id")
        if raw:
            got = str(raw).strip().upper()
            got = canonical_problem_id(got) or got
            if got != target:
                return (
                    f"This prove session targets {target}. Call {name} with "
                    f"problem_id='{target}', not '{got}' — do not work on another dossier."
                )
        # Block reading/writing inside a *different* dossier's directory: this is a
        # single-problem session, not a queue — the model must not wander to another
        # PROBLEM-* via a file path (read_file/write_file/apply_patch).
        path = args.get("path")
        if path:
            match = _DOSSIER_PATH.search(str(path))
            if match:
                other = canonical_problem_id(match.group(1).upper()) or match.group(1).upper()
                if other != target:
                    return (
                        f"This prove session targets {target}; do not read or modify other "
                        f"dossiers (path references {other}). Stay on {target} — it is one "
                        "problem, not a research queue."
                    )
        if name == "run_shell":
            cmd = str(args.get("command", "")).strip()
            if is_package_install_command(cmd):
                return (
                    "Blocked: do not install Python/system packages via run_shell. "
                    "Run 'opentorus env prepare python-sci --file docker/Dockerfile', then "
                    "exp_new(..., environment='python-sci') and exp_run(exp_id=...)."
                )
            return _PROVE_RUN_SHELL_BLOCK
        return None

    return gate
