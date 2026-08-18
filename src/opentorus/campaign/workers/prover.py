"""The prover: a bounded proof-writing loop whose gaps become obligations.

It reuses the ``prove`` machinery as is — :func:`build_prove_prompt` (neutral
"prove or refute" framing, branch objective and assumption context appended as
*additional instructions* together with the failure signatures already recorded on
the branch), the ``prove_tool_gate`` (dossier writes pinned to this problem, no CLI
re-entry) and, on a branch's first attempt, the ``proof_write`` deliverable bootstrap
(:func:`bootstrap_proof_write_args`) so a model that only chats still leaves a
scaffold sketch with an explicit gap. Later attempts on the same branch run in
gap-fill mode: no bootstrap, a session gate that only opens once ``proof_write`` was
called again, and the standard gap-fill hint.

What comes back is honest by construction: every explicit gap of the new/updated
PROOF attempt (``nl_proof.explicit_gaps``) is proposed as an obligation whose closure
modes name the artifact classes that could discharge it; a gap-free sketch proposes
one whole-proof obligation instead (a sketch without gaps is still a sketch until a
referee or a formal backend accepts it). No ``proof_write`` in the whole budget is a
``model_no_progress`` failure signature, never a silent "completed".
"""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.failures import build_failure_signature
from opentorus.campaign.models import (
    ArtifactRef,
    ClosureMode,
    CostTotals,
    ObligationProposal,
    RootRelation,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import (
    WorkerRuntime,
    acquire_lease,
    bounded_loop,
    formal_backends,
)
from opentorus.errors import OpenTorusError

GAP_CLOSURE_MODES: list[ClosureMode] = [
    ClosureMode.nl_proof_referee_accepted,
    ClosureMode.formal_proof,
    ClosureMode.smt_certificate,
    ClosureMode.exact_symbolic_certificate,
]

# Branches whose proof *is* an answer to the dossier problem write the dossier's one
# primary sketch; every other relation (special case, obstruction, relaxation, …)
# writes an exploration-scoped sketch with an explicit bridge, so it can never be
# mistaken for — or silently overwrite — the primary answer.
PRIMARY_RELATIONS: frozenset[RootRelation] = frozenset(
    {
        RootRelation.equivalent,
        RootRelation.sufficient,
        RootRelation.necessary,
        RootRelation.counterexample_route,
    }
)

GAP_FILL_HINT = (
    "This branch already holds a primary proof_write with open [GAP-n] markers — the "
    "work item is NOT complete until proof_write(scope=primary) is called again to fill "
    "or shrink the gaps. Read the latest PROOF-*, use paper_read / exp_run as needed, then "
    "call proof_write. A chat summary does not finish this work item."
)


def branch_instructions(ctx: WorkerContext) -> str:
    """The branch-specific block appended to the prove prompt as extra instructions."""
    lines = [
        f"Campaign branch {ctx.branch_id or '(none)'} — objective: {ctx.branch_objective}",
    ]
    if ctx.strategy_summary:
        lines.append(f"Strategy: {ctx.strategy_summary}")
    lines.append(f"Relation of this branch to the root problem: {ctx.root_relation.value}.")
    if ctx.root_relation not in PRIMARY_RELATIONS:
        lines.append(
            "This branch is NOT the dossier's primary answer: write proof_write with "
            "scope=exploration and connection_to_dossier stating how this branch bears on "
            "the root problem; never scope=primary here."
        )
    if ctx.assumption_context:
        lines.append("Assumption context (state every one you use):")
        lines.extend(f"  - {a}" for a in ctx.assumption_context)
    if ctx.failure_signatures:
        lines.append(
            "Failed attempts already recorded on this branch — do NOT repeat them "
            "unchanged; change an assumption, a tool, or the obligation, or record why "
            "the same route is worth another try:"
        )
        for sig in ctx.failure_signatures:
            lines.append(
                f"  - {sig.signature_id or 'FSIG'} [{sig.error_category}] "
                f"{sig.strategy_class}: {sig.counterargument or '(no counterargument)'} "
                f"(seen {sig.occurrences}x)"
            )
    if ctx.open_obligations:
        lines.append("Open obligations on this branch:")
        lines.extend(f"  - {ob.obligation_id}: {ob.statement}" for ob in ctx.open_obligations[:12])
    return "\n".join(lines)


def statement_focus(ctx: WorkerContext) -> str:
    problem = ctx.root_problem
    parts = [problem.statement.strip() or problem.title]
    if problem.assumptions:
        parts.append("Recorded assumptions:\n" + "\n".join(f"- {a}" for a in problem.assumptions))
    if problem.definitions:
        parts.append("Definitions:\n" + "\n".join(f"- {d}" for d in problem.definitions[:12]))
    return "\n\n".join(p for p in parts if p)


def bootstrap_args(ctx: WorkerContext) -> dict[str, object]:
    """The ``proof_write`` bootstrap for a branch's first attempt.

    Primary-relation branches scaffold the dossier's primary sketch (theorem = the
    statement); every other branch scaffolds an *exploration* sketch whose theorem is
    the branch objective and whose ``connection_to_dossier`` names the relation — the
    tool refuses an exploration sketch without a bridge, and a primary write from a
    special-case branch would refine the real primary answer in place.
    """
    from opentorus.research.dossier.nl_proof import bootstrap_proof_write_args

    pid = ctx.root_problem.problem_id
    if ctx.root_relation in PRIMARY_RELATIONS:
        return dict(
            bootstrap_proof_write_args(
                pid,
                f"Natural-language proof sketch for {pid}",
                statement=ctx.root_problem.statement,
            )
        )
    objective = ctx.branch_objective.strip() or f"{ctx.root_relation.value} route for {pid}"
    args = dict(
        bootstrap_proof_write_args(
            pid, f"{ctx.root_relation.value} sketch for {pid}", statement=objective
        )
    )
    args["scope"] = "exploration"
    statement = ctx.root_problem.statement.strip() or ctx.root_problem.title or pid
    # The relevance check wants the bridge to name the dossier problem itself, so the
    # statement is quoted verbatim alongside the relation.
    args["connection_to_dossier"] = (
        f"Campaign branch {ctx.branch_id or '(none)'} relates to the dossier problem "
        f"\"{statement}\" as '{ctx.root_relation.value}': {objective} — settling it does not "
        "settle the root problem by itself."
    )
    return args


def _proof_body(ot_dir: Path, body_path: str | None) -> str:
    if not body_path:
        return ""
    path = ot_dir / body_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


class ProverWorker:
    role = WorkerRole.prover

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.agent.prove_gate import prove_tool_gate
        from opentorus.agent.prove_loop import build_prove_prompt
        from opentorus.research.dossier import store
        from opentorus.research.dossier.nl_proof import explicit_gaps, gap_marker_key

        pid = ctx.root_problem.problem_id
        strategy = ctx.strategy_key or "proof_sketch"
        before = {p.id: p.updated_at for p in store.list_proof_attempts(rt.ot_dir, pid)}
        try:
            lease = acquire_lease(ctx, rt)
        except OpenTorusError as exc:
            return WorkerResult(
                status="failed",
                error_category="tool_unavailable",
                message=f"no eligible provider: {exc}",
                usage=CostTotals(steps=1),
                failure_signature=build_failure_signature(
                    role=self.role,
                    strategy_class=strategy,
                    assumption_context=ctx.assumption_context,
                    tool_or_solver="provider",
                    error_category="tool_unavailable",
                    counterargument=f"no eligible provider for {ctx.task_class}",
                    verifier_backends=formal_backends(rt.config),
                ),
            )
        prior = [a for a in ctx.branch_artifact_ids if a.startswith("PROOF-") and a in before]
        prompt = build_prove_prompt(
            pid,
            literature_first=False,
            statement_focus=statement_focus(ctx),
            extra=branch_instructions(ctx),
            formal_backends=formal_backends(rt.config),
        )
        gate = prove_tool_gate(pid, deliverable_done=lambda: False)
        primary = ctx.root_relation in PRIMARY_RELATIONS
        if not prior:
            loop = bounded_loop(
                ctx,
                rt,
                lease=lease,
                tool_gate=gate,
                deliverable_bootstrap=("proof_write", bootstrap_args(ctx)),
                # A non-primary branch's exploration sketch *is* its deliverable.
                deliverable_satisfied_by=None if primary else (lambda _name, result: result.ok),
            )
        else:

            def _proof_written() -> bool:
                now = {p.id: p.updated_at for p in store.list_proof_attempts(rt.ot_dir, pid)}
                return any(pid_ not in before or before[pid_] != ts for pid_, ts in now.items())

            loop = bounded_loop(
                ctx,
                rt,
                lease=lease,
                tool_gate=gate,
                session_gate=_proof_written,
                session_recovery_hint=lambda: GAP_FILL_HINT,
            )
        loop.run(prompt)
        after = {p.id: p for p in store.list_proof_attempts(rt.ot_dir, pid)}
        changed = sorted(
            p_id for p_id, p in after.items() if p_id not in before or before[p_id] != p.updated_at
        )
        turns = max(1, loop.steps_run)
        decision_id = lease.decision.decision_id
        if not changed:
            return WorkerResult(
                status="failed",
                error_category="model_no_progress",
                message=f"no proof_write in {turns} model turn(s)",
                usage=CostTotals(steps=turns),
                routing_decision_id=decision_id,
                notes=[f"{turns} turn(s), {loop.tool_calls_this_run} tool call(s), no proof_write"],
                failure_signature=build_failure_signature(
                    role=self.role,
                    strategy_class=strategy,
                    assumption_context=ctx.assumption_context,
                    tool_or_solver="proof_write",
                    error_category="model_no_progress",
                    counterargument=(
                        "gap-fill turns produced no proof_write"
                        if prior
                        else "no proof_write and no bootstrap"
                    ),
                    verifier_backends=formal_backends(rt.config),
                ),
            )
        newest_id = max(changed, key=lambda i: (after[i].updated_at, i))
        proof = after[newest_id]
        gaps = explicit_gaps(gaps=list(proof.gaps), body=_proof_body(rt.ot_dir, proof.body_path))
        known = {ob.statement.strip().lower() for ob in ctx.open_obligations}
        obligations: list[ObligationProposal] = []
        for n, gap in enumerate(gaps, start=1):
            if gap.strip().lower() in known:
                continue
            obligations.append(
                ObligationProposal(
                    statement=gap,
                    assumptions=list(ctx.assumption_context),
                    root_relation=ctx.root_relation,
                    closure_modes=list(GAP_CLOSURE_MODES),
                    source_proof_id=proof.id,
                    gap_marker=gap_marker_key(gap) or f"GAP-{n}",
                    supporting_artifacts=[proof.id],
                )
            )
        if not gaps and f"whole proof {proof.id}".lower() not in known:
            obligations.append(
                ObligationProposal(
                    statement=f"Whole proof {proof.id}: {proof.title or 'sketch'} must be accepted",
                    assumptions=list(ctx.assumption_context),
                    root_relation=ctx.root_relation,
                    closure_modes=list(GAP_CLOSURE_MODES),
                    source_proof_id=proof.id,
                    gap_marker=None,
                    supporting_artifacts=[proof.id],
                )
            )
        return WorkerResult(
            status="completed",
            artifacts_created=[
                ArtifactRef(artifact_id=p_id, kind="proof_attempt", branch_id=ctx.branch_id)
                for p_id in changed
            ],
            obligations=obligations,
            usage=CostTotals(steps=turns),
            routing_decision_id=decision_id,
            notes=[
                f"{proof.id} ({proof.status}, scope {proof.scope}) with {len(gaps)} open gap(s); "
                f"{len(obligations)} new obligation(s) proposed",
                f"{turns} model turn(s), bootstrap used: {loop.bootstrap_used}",
            ],
        )


__all__ = [
    "GAP_CLOSURE_MODES",
    "GAP_FILL_HINT",
    "PRIMARY_RELATIONS",
    "ProverWorker",
    "bootstrap_args",
    "branch_instructions",
]
