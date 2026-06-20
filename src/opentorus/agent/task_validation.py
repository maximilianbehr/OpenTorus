"""Validate planned-task deliverables against the result contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from opentorus.research.tasks import Task


@dataclass
class ArtifactSnapshot:
    papers: int = 0
    problems: int = 0
    claims: int = 0
    experiments: int = 0
    memory_entries: int = 0
    analysis_md: bool = False
    tool_names: list[str] = field(default_factory=list)


@dataclass
class ContractCheck:
    ok: bool
    detail: str


def snapshot_artifacts(root: Path, ot_dir: Path) -> ArtifactSnapshot:
    from opentorus.research.claims import list_claims
    from opentorus.research.dossier.store import list_dossiers
    from opentorus.research.experiments import list_experiments
    from opentorus.research.memory import VALID_KINDS, list_memory
    from opentorus.research.papers import list_papers

    mem = sum(len(list_memory(ot_dir, kind)) for kind in VALID_KINDS)
    return ArtifactSnapshot(
        papers=len(list_papers(ot_dir)),
        problems=len(list_dossiers(ot_dir)),
        claims=len(list_claims(ot_dir)),
        experiments=len(list_experiments(ot_dir)),
        memory_entries=mem,
        analysis_md=(root / "analysis.md").is_file(),
    )


def _delta(before: ArtifactSnapshot, after: ArtifactSnapshot) -> ArtifactSnapshot:
    return ArtifactSnapshot(
        papers=after.papers - before.papers,
        problems=after.problems - before.problems,
        claims=after.claims - before.claims,
        experiments=after.experiments - before.experiments,
        memory_entries=after.memory_entries - before.memory_entries,
        analysis_md=after.analysis_md and not before.analysis_md,
        tool_names=[t for t in after.tool_names if t not in before.tool_names],
    )


def check_task_contract(
    task: Task,
    *,
    before: ArtifactSnapshot,
    after: ArtifactSnapshot,
    tools: set[str],
    edited: bool,
) -> ContractCheck:
    """Return whether the task category's deliverable contract was satisfied."""
    delta = _delta(before, after)
    cat = task.category
    ok = False
    detail = ""

    if cat == "literature":
        ok = (
            delta.papers > 0
            or delta.memory_entries > 0
            or bool(
                tools
                & {
                    "paper_fetch",
                    "paper_add",
                    "paper_ingest",
                    "lit_search",
                    "paper_extract_problems",
                    "memory_add",
                }
            )
        )
        detail = "Expected paper_fetch, lit_search, paper_extract_problems, or memory_add."
    elif cat == "code":
        ok = edited or bool(tools & {"write_file", "apply_patch", "run_shell", "check"})
        detail = "Expected write_file, apply_patch, or run_shell with edits."
    elif cat == "experiment":
        ok = (
            delta.experiments > 0
            or bool(tools & {"exp_run", "exp_new"})
            or bool(tools & {"run_shell"})
        )
        detail = "Expected exp_new + exp_run, or a new EXP-* artifact."
    elif cat in {"analysis", "report"}:
        ok = (
            delta.analysis_md
            or delta.memory_entries > 0
            or delta.claims > 0
            or bool(
                tools
                & {
                    "memory_add",
                    "claim_new",
                    "evidence_add",
                    "write_file",
                    "proof_write",
                }
            )
        )
        detail = "Expected analysis.md, proof_write, memory_add, claim_new, or write_file."
    elif cat == "review":
        ok = bool(tools & {"claim_new", "evidence_add", "memory_add"}) or delta.claims > 0
        detail = "Expected review notes via memory_add, claim_new, or evidence_add."
    else:
        ok = True
        detail = ""

    if ok:
        return ContractCheck(ok=True, detail="Deliverable contract satisfied.")
    return ContractCheck(ok=False, detail=detail)


def validate_task_contract(
    task: Task,
    before: ArtifactSnapshot,
    after: ArtifactSnapshot,
    *,
    tool_calls: int,
    edited: bool,
) -> ContractCheck:
    """Validate a planned task against before/after workspace snapshots."""
    tools = set(after.tool_names)
    if tool_calls <= 0:
        return ContractCheck(
            ok=False,
            detail="No tool calls recorded — chat-only replies do not satisfy the contract.",
        )
    return check_task_contract(
        task,
        before=before,
        after=after,
        tools=tools,
        edited=edited,
    )
