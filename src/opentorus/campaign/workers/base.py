"""Worker contract and the helpers every worker builds on.

A worker is a narrow role: it receives a frozen :class:`WorkerContext` (ids, artifact
references, budget, allowed tools — never a transcript) and a :class:`WorkerRuntime`
(the engine's shared services), does one bounded piece of work, and returns a
:class:`WorkerResult` describing what it produced. The engine turns the result into
events; the worker never writes campaign events itself and never sets a claim status.

:func:`bounded_loop` is how a model-driven worker gets an ``AgentLoop``: leased
provider from the pool (so routing is real and recorded), the work item's step cap,
its own session id, the campaign usage tags on every ledger row, the engine's event
sink, its cancellation flag, and a tool gate that enforces ``allowed_tools``.
:func:`snapshot_artifacts` / :func:`diff_artifacts` let the engine derive
``artifact_created`` events from what changed in the dossier during a run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from opentorus.campaign.clock import Clock, SystemClock
from opentorus.campaign.models import (
    ArtifactRef,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.config import Config

if TYPE_CHECKING:
    from opentorus.agent.control.events import RunEventSink
    from opentorus.agent.loop import AgentLoop, ConfirmCallback
    from opentorus.providers.pool import ProviderLease, ProviderPool
    from opentorus.tools.base import ToolResult
    from opentorus.tools.registry import ToolRegistry

RegistryFactory = Callable[[str | None], "ToolRegistry"]


@dataclass
class WorkerRuntime:
    """The engine's services a worker may use (shared, not per work item)."""

    root: Path
    ot_dir: Path
    config: Config
    pool: ProviderPool
    clock: Clock = field(default_factory=SystemClock)
    event_sink: RunEventSink | None = None
    confirm: ConfirmCallback | None = None
    registry_factory: RegistryFactory | None = None
    should_stop: Callable[[], bool] | None = None

    def registry(self, problem_id: str | None) -> ToolRegistry:
        if self.registry_factory is not None:
            return self.registry_factory(problem_id)
        from opentorus.tools.builtin import build_default_registry

        return build_default_registry(self.root, self.ot_dir, self.config, problem_id=problem_id)


class Worker(Protocol):
    """``run`` does one bounded piece of work and reports; it must not raise for
    ordinary failures (return ``status="failed"`` with an error category instead)."""

    role: WorkerRole

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult: ...


def usage_tags(ctx: WorkerContext) -> dict[str, str]:
    """The attribution stamped on every usage-ledger row a worker's loop writes."""
    tags = {"campaign_id": ctx.campaign_id, "worker_role": ctx.role.value}
    if ctx.branch_id:
        tags["branch_id"] = ctx.branch_id
    if ctx.work_item_id:
        tags["work_item_id"] = ctx.work_item_id
    return tags


def allowed_tools_gate(allowed: frozenset[str]) -> Callable[[str, dict], str | None] | None:
    """A tool gate refusing anything outside ``allowed`` (``None`` when unrestricted)."""
    if not allowed:
        return None

    def _gate(name: str, _args: dict) -> str | None:
        if name in allowed:
            return None
        return (
            f"Blocked {name}: this worker may only use {', '.join(sorted(allowed))} "
            "(campaign worker isolation)."
        )

    return _gate


# The tools each model-driven role may call. Restricting the registry (not only
# gating it) matters twice: a worker cannot wander outside its role, and the mock
# provider — which keys on tool *names* it sees — never gets distracted by ``status``
# / ``memory_list`` and reaches its deliverable bootstrap in a fixed number of turns.
_DOSSIER_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "list_files",
        "glob_files",
        "memory_add",
        "paper_list",
        "paper_read",
        "paper_fetch",
        "lit_search",
        "claim_new",
        "evidence_add",
        "kb_query",
    }
)
ROLE_ALLOWED_TOOLS: dict[WorkerRole, frozenset[str]] = {
    WorkerRole.strategist: frozenset(),
    WorkerRole.prover: _DOSSIER_TOOLS
    | {
        "proof_write",
        "proof_submit",
        "exp_new",
        "exp_run",
        "dossier_known_result_add",
        "dossier_related_paper_add",
    },
    WorkerRole.falsifier: _DOSSIER_TOOLS | {"exp_new", "exp_run"},
    WorkerRole.numerical_experimenter: _DOSSIER_TOOLS | {"exp_new", "exp_run"},
    WorkerRole.symbolic_experimenter: _DOSSIER_TOOLS | {"exp_new", "exp_run", "proof_submit"},
    WorkerRole.formalizer: _DOSSIER_TOOLS | {"proof_submit", "proof_write"},
    WorkerRole.librarian: _DOSSIER_TOOLS
    | {"paper_add", "dossier_known_result_add", "dossier_related_paper_add"},
    WorkerRole.critic: frozenset(),
    WorkerRole.verifier_coordinator: frozenset(),
    WorkerRole.synthesizer: frozenset(),
}


def restricted_registry(full: ToolRegistry, allowed: frozenset[str]) -> ToolRegistry:
    """A registry holding only the ``allowed`` tools of ``full`` (all of them when
    ``allowed`` is empty)."""
    from opentorus.tools.registry import ToolRegistry as _Registry

    if not allowed:
        return full
    out = _Registry()
    for tool in full.tools():
        if tool.name in allowed:
            out.register(tool)
    return out


def is_mock_provider(provider: object) -> bool:
    """The deterministic mock is the offline path: workers skip model-driven loops."""
    return getattr(provider, "name", "") == "mock"


def acquire_lease(ctx: WorkerContext, rt: WorkerRuntime) -> ProviderLease:
    """Lease the provider for the worker's task class, tagged for the routing ledger."""
    return rt.pool.acquire(ctx.task_class, tags={**usage_tags(ctx), "session_id": ctx.session_id})


def formal_backends(config: Config) -> list[str]:
    """Proof-assistant / SMT backends enabled in config (certificate checkers such as
    ``sympy`` and ``interval`` are not formalization targets)."""
    from opentorus.tools.research import enabled_verifier_backends

    return [b for b in enabled_verifier_backends(config) if b in ("lean4", "coq", "smt")]


def bounded_loop(
    ctx: WorkerContext,
    rt: WorkerRuntime,
    *,
    lease: ProviderLease,
    registry: ToolRegistry | None = None,
    tool_gate: Callable[[str, dict], str | None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    deliverable_satisfied_by: Callable[[str, ToolResult], bool] | None = None,
    **loop_kwargs: object,
) -> AgentLoop:
    """An ``AgentLoop`` bounded by the work item: its steps, session, tags, sink, stop flag.

    ``lease`` comes from ``rt.pool.acquire(ctx.task_class, ...)`` so the routing
    decision id lands on every usage row (``routing=lease.decision``). ``tool_gate``
    stacks behind the ``allowed_tools`` gate; ``loop_kwargs`` are passed through for
    deliverable callbacks (bootstrap, gates) that individual workers need.
    ``deliverable_satisfied_by`` overrides the loop's notion of *which* deliverable
    result counts (by default only a primary-scope ``proof_write`` does — a
    special-case branch writing exploration sketches would otherwise be bootstrapped
    again on every chat turn).
    """
    from opentorus.agent.loop import AgentLoop

    isolation = allowed_tools_gate(ctx.allowed_tools)

    def _gate(name: str, args: dict) -> str | None:
        if isolation is not None:
            blocked = isolation(name, args)
            if blocked:
                return blocked
        if tool_gate is not None:
            return tool_gate(name, args)
        return None

    def _stop() -> bool:
        if should_stop is not None and should_stop():
            return True
        return bool(rt.should_stop is not None and rt.should_stop())

    loop = AgentLoop(
        rt.root,
        rt.ot_dir,
        lease.provider,
        restricted_registry(
            registry or rt.registry(ctx.root_problem.problem_id), ctx.allowed_tools
        ),
        rt.config,
        max_steps=ctx.budget.max_steps,
        session_id=ctx.session_id,
        confirm=rt.confirm,
        tool_gate=_gate,
        event_sink=rt.event_sink,
        routing=lease.decision,
        usage_tags=usage_tags(ctx),
        should_stop=_stop,
        **loop_kwargs,  # type: ignore[arg-type]
    )
    if deliverable_satisfied_by is not None:
        # The loop exposes the bootstrap but not the satisfaction rule; the policy object
        # is the documented seam (``DeliverablePolicy.satisfied_by``), reached here so
        # workers never touch the loop's internals themselves.
        loop._deliverable.satisfied_by = deliverable_satisfied_by
    return loop


# --------------------------------------------------------------------------------------
# artifact snapshots
# --------------------------------------------------------------------------------------

ArtifactIndex = dict[str, set[str]]


def snapshot_artifacts(ot_dir: Path, problem_id: str) -> ArtifactIndex:
    """``kind -> ids`` for every dossier/workspace artifact attributable to the problem.

    Taken before and after a worker runs; the difference is what the worker created.
    Reads only; tolerant of missing ledgers (a fresh dossier has empty ones).
    """
    from opentorus.research.dossier import store
    from opentorus.research.dossier.experiments import list_problem_experiments
    from opentorus.research.theorems import store as thm_store
    from opentorus.research.verifiers.proofs import list_proofs

    pid = problem_id.strip().upper()
    index: ArtifactIndex = {}
    if store.get_dossier(ot_dir, pid) is None:
        return index
    index["claim"] = {c.id for c in store.list_claims(ot_dir, pid)}
    index["evidence"] = {e.id for e in store.list_evidence(ot_dir, pid)}
    index["proof_attempt"] = {p.id for p in store.list_proof_attempts(ot_dir, pid)}
    index["failed_attempt"] = {f.id for f in store.list_failed_attempts(ot_dir, pid)}
    index["approach"] = {a.id for a in store.list_approaches(ot_dir, pid)}
    index["theorem_ref"] = {t.id for t in store.list_theorem_refs(ot_dir, pid)}
    index["known_result"] = {k.id for k in store.list_known_results(ot_dir, pid)}
    index["related_paper"] = {p.id for p in store.list_related_papers(ot_dir, pid)}
    try:
        index["experiment"] = {e.experiment_id for e in list_problem_experiments(ot_dir, pid)}
    except Exception:  # noqa: BLE001 - a broken manifest must not hide the rest
        index["experiment"] = set()
    index["proof"] = {
        p.id for p in list_proofs(ot_dir) if p.problem_id is None or p.problem_id == pid
    }
    index["theorem_reference"] = {r.id for r in thm_store.list_references(ot_dir, problem_id=pid)}
    index["coverage"] = {c.id for c in thm_store.list_coverage_history(ot_dir, pid)}
    return index


def diff_artifacts(
    before: ArtifactIndex,
    after: ArtifactIndex,
    *,
    branch_id: str | None = None,
    work_item_id: str | None = None,
    role: WorkerRole | None = None,
) -> list[ArtifactRef]:
    """Artifact refs for ids present in ``after`` but not ``before`` (sorted, stable)."""
    refs: list[ArtifactRef] = []
    for kind in sorted(after):
        new_ids = after[kind] - before.get(kind, set())
        for aid in sorted(new_ids):
            refs.append(
                ArtifactRef(
                    artifact_id=aid,
                    kind=kind,
                    branch_id=branch_id,
                    work_item_id=work_item_id,
                    role=role,
                )
            )
    return refs


__all__ = [
    "ROLE_ALLOWED_TOOLS",
    "ArtifactIndex",
    "RegistryFactory",
    "Worker",
    "WorkerRuntime",
    "acquire_lease",
    "allowed_tools_gate",
    "bounded_loop",
    "diff_artifacts",
    "formal_backends",
    "is_mock_provider",
    "restricted_registry",
    "snapshot_artifacts",
    "usage_tags",
]
