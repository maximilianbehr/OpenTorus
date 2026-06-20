"""Bootstrap first tool calls when a planned task model returns chat-only."""

from __future__ import annotations

import re
from pathlib import Path

from opentorus.agent.prompts import TASK_CATEGORY_HINTS
from opentorus.research.tasks import Task


def _problem_id_from_text(text: str) -> str | None:
    match = re.search(r"PROBLEM-\d{4}", text, re.IGNORECASE)
    return match.group(0).upper() if match else None


def _latest_dossier_experiment(ot_dir: Path, problem_id: str):
    from opentorus.research.dossier.experiments import list_experiments as list_dossier_experiments

    exps = list_dossier_experiments(ot_dir, problem_id)
    return exps[-1] if exps else None


def _latest_experiment_id(ot_dir: Path) -> str | None:
    from opentorus.research.experiments import list_experiments

    exps = list_experiments(ot_dir)
    return exps[-1].id if exps else None


def _completed_experiment_for_scripts(root: Path, ot_dir: Path) -> str | None:
    """Prefer a completed EXP-* that runs a known workspace verification script."""
    from opentorus.research.experiments import find_experiment_by_command, list_experiments

    for sub in ("scripts", "."):
        folder = root if sub == "." else root / sub
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("verify*.py"))[:3]:
            rel = path.relative_to(root).as_posix()
            for flag in ("--all", ""):
                cmd = f"python {rel}{(' ' + flag) if flag else ''}".strip()
                existing = find_experiment_by_command(ot_dir, cmd)
                if existing is not None and existing.status == "completed":
                    return existing.id
    for exp in reversed(list_experiments(ot_dir)):
        if exp.status == "completed":
            return exp.id
    return None


def recovery_hint_for_task(task: Task, *, attempt: int) -> str:
    """Short, category-specific nudge (not persisted to session)."""
    plan = TASK_CATEGORY_HINTS.get(task.category, "Call status once, then produce the deliverable.")
    return (
        f"Attempt {attempt}: {plan} Do not repeat list_files or run_shell find/ls. "
        "If a filename is in the goal or Research artifacts block, read_file it now — "
        "do not ask the user for permission. "
        f"Call a deliverable tool now (proof_write, write_file, exp_run, memory_add, …)."
    )


def _report_bootstrap_title(task: Task) -> str:
    goal = (task.goal or "").strip()
    if len(goal) <= 72 and goal and not goal.lower().startswith("write_file"):
        return goal[0].upper() + goal[1:]
    return "Final investigation report"


def _task_wants_nl_proof(goal: str) -> bool:
    g = goal.lower()
    return any(
        w in g
        for w in (
            "proof",
            "prove",
            "beweis",
            "beweisen",
            "theorem",
            "sketch",
            "lemma",
            "widerleg",
            "refute",
        )
    )


def bootstrap_tool_for_task(task: Task, root: Path, ot_dir: Path) -> tuple[str, dict] | None:
    """Pick a sensible first tool when the model will not call tools."""
    problem_id = _problem_id_from_text(task.goal)
    if task.category == "experiment":
        if problem_id:
            dossier_exp = _latest_dossier_experiment(ot_dir, problem_id)
            if dossier_exp is not None:
                rel = (
                    f".opentorus/problems/{problem_id}/experiments/"
                    f"{dossier_exp.experiment_id}/run.sh"
                )
                if (root / rel).is_file():
                    return "run_shell", {"command": f"bash {rel}"}
                manifest = (
                    f".opentorus/problems/{problem_id}/experiments/"
                    f"{dossier_exp.experiment_id}/manifest.yaml"
                )
                if (root / manifest).is_file():
                    return "read_file", {"path": manifest}
        completed = _completed_experiment_for_scripts(root, ot_dir)
        if completed:
            return "memory_add", {
                "kind": "decisions",
                "text": (
                    f"{completed} already completed for this workspace script — "
                    "cite it in claims; do not exp_new or exp_run again."
                ),
            }
        exp_id = _latest_experiment_id(ot_dir)
        if exp_id:
            return "exp_run", {"exp_id": exp_id}
        if problem_id:
            rel = f".opentorus/problems/{problem_id}/experiments"
            if (root / rel).is_dir():
                return "list_files", {"path": rel}
        return "status", {}

    if task.category == "report":
        return "write_file", {
            "path": "analysis.md",
            "content": (
                "# Investigation summary\n\n"
                "_Summarize findings with local artifact ids (CLAIM-*, EXP-*, PAPER-*)._\n"
            ),
        }

    if task.category == "analysis":
        if problem_id and _task_wants_nl_proof(task.goal):
            from opentorus.research.dossier.nl_proof import bootstrap_proof_write_args

            return "proof_write", bootstrap_proof_write_args(problem_id, task.goal)
        if problem_id:
            statement = f".opentorus/problems/{problem_id}/statement.md"
            if (root / statement).is_file():
                return "read_file", {"path": statement}
        from opentorus.research.experiments import list_experiments

        for exp in reversed(list_experiments(ot_dir)):
            if exp.status != "completed":
                continue
            summary = ot_dir / exp.path / "summary.md"
            if summary.is_file():
                rel = summary.relative_to(root).as_posix()
                return "read_file", {"path": rel}
        return "status", {}

    if task.category == "literature":
        return "paper_list", {}

    if task.category == "review":
        return "memory_list", {}

    return "status", {}
