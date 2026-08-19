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

Scope is enforced by the tool gate, not by prompt text: only a branch whose relation
to the root is ``equivalent`` writes the dossier's one primary sketch. Every other
branch (special case, relaxation, sufficient, necessary, supporting, unknown, ...) has
its ``proof_write`` calls rewritten to ``scope=exploration`` with a bridge naming the
branch objective (:func:`scope_gate`) — a real run showed a special-case prover
refining ``PROOF-0001`` in place and re-proposing the proof branch's obligations,
because the model ignored the instruction and the default scope is ``primary``.

What comes back is honest by construction: every explicit gap of the new/updated
PROOF attempt (``nl_proof.explicit_gaps``) is proposed as an obligation whose closure
modes name the artifact classes that could discharge it; a gap-free sketch proposes
one whole-proof obligation instead (a sketch without gaps is still a sketch until a
referee or a formal backend accepts it). The obligations of a non-primary branch are
derived from the exploration sketch *it* wrote, never from the primary. No
``proof_write`` in the whole budget is a ``model_no_progress`` failure signature,
never a silent "completed".
"""

from __future__ import annotations

from collections.abc import Callable
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

# Only a branch whose target *is* the root problem writes the dossier's one primary
# sketch. A sufficient condition, a necessary condition or a counterexample route is
# still its own statement (settling it needs a verified reduction, a converse or an
# accepted witness — see proof_tree.settlement), so its sketch is exploration-scoped
# with an explicit bridge: it can never be mistaken for — or silently overwrite — the
# primary answer, and its gaps never duplicate the proof branch's obligations.
PRIMARY_RELATIONS: frozenset[RootRelation] = frozenset({RootRelation.equivalent})

# The tool's own threshold for ``connection_to_dossier`` (``proof_write`` says
# ">=60 chars"); a shorter bridge gets the branch bridge appended before the call.
MIN_BRIDGE_CHARS = 60

GAP_FILL_HINT = (
    "This branch already holds a primary proof_write with open [GAP-n] markers — the "
    "work item is NOT complete until proof_write(scope=primary) is called again to fill "
    "or shrink the gaps. Read the latest PROOF-*, use paper_read / exp_run as needed, then "
    "call proof_write. A chat summary does not finish this work item."
)
EXPLORATION_GAP_FILL_HINT = (
    "This branch already holds an exploration proof_write with open [GAP-n] markers — the "
    "work item is NOT complete until proof_write(scope=exploration, connection_to_dossier="
    "...) is called again to fill or shrink the gaps of THIS branch's sketch. Read the "
    "latest exploration PROOF-* of this branch, use paper_read / exp_run as needed, then "
    "call proof_write. Do not touch the dossier's primary sketch."
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
            "the root problem; never scope=primary here (a primary write from this branch "
            "is rewritten to scope=exploration by the tool gate)."
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
    args = dict(
        bootstrap_proof_write_args(
            pid, f"{ctx.root_relation.value} sketch for {pid}", statement=branch_objective(ctx)
        )
    )
    args["scope"] = "exploration"
    args["connection_to_dossier"] = connection_text(ctx)
    return args


def branch_objective(ctx: WorkerContext) -> str:
    """The branch objective, or a relation-named stand-in when the strategist left it empty."""
    pid = ctx.root_problem.problem_id
    return ctx.branch_objective.strip() or f"{ctx.root_relation.value} route for {pid}"


def connection_text(ctx: WorkerContext) -> str:
    """The ``connection_to_dossier`` bridge for a non-primary branch's exploration sketch.

    The relevance check wants the bridge to name the dossier problem itself, so the
    statement is quoted verbatim alongside the relation and the branch objective; the
    closing clause states what the relation means for the root, so the sketch cannot be
    read as the dossier answer.
    """
    pid = ctx.root_problem.problem_id
    statement = ctx.root_problem.statement.strip() or ctx.root_problem.title or pid
    return (
        f"Campaign branch {ctx.branch_id or '(none)'} relates to the dossier problem "
        f"\"{statement}\" as '{ctx.root_relation.value}': {branch_objective(ctx)} — settling "
        "it does not settle the root problem by itself."
    )


def scope_gate(
    ctx: WorkerContext,
    inner: Callable[[str, dict], str | None],
    *,
    coercions: list[str],
) -> Callable[[str, dict], str | None]:
    """Wrap ``inner`` so a non-primary branch can only write exploration sketches.

    The gate receives the live argument dict of the call the loop is about to execute
    (the loop validates and runs exactly this dict), so rewriting ``scope`` and the
    bridge *here* is the coercion — the model's text is not trusted to remember the
    instruction, and a blocked call would only cost a smaller model more turns. Every
    rewrite is appended to ``coercions`` (the scope the model asked for) so the worker
    can report it. A primary-relation branch gets ``inner`` back unchanged.
    """
    if ctx.root_relation in PRIMARY_RELATIONS:
        return inner

    def gate(name: str, args: dict) -> str | None:
        if name == "proof_write":
            asked = str(args.get("scope") or "").strip().lower()
            coerced = asked != "exploration"
            if coerced:
                args["scope"] = "exploration"
                coercions.append(asked or "(missing)")
            bridge = str(args.get("connection_to_dossier") or "").strip()
            if coerced or len(bridge) < MIN_BRIDGE_CHARS:
                # Keep whatever the model said and add the branch bridge, which quotes
                # the statement verbatim so the tool's relevance check passes.
                args["connection_to_dossier"] = "\n\n".join(
                    part for part in (bridge, connection_text(ctx)) if part
                )
        return inner(name, args)

    return gate


def _proof_body(ot_dir: Path, problem_id: str, body_path: str | None) -> str:
    """The sketch's markdown (``body_path`` is relative to the dossier directory)."""
    from opentorus.research.dossier.store import dossier_dir

    if not body_path:
        return ""
    path = dossier_dir(ot_dir, problem_id) / body_path
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
        primary = ctx.root_relation in PRIMARY_RELATIONS
        coercions: list[str] = []
        gate = scope_gate(
            ctx, prove_tool_gate(pid, deliverable_done=lambda: False), coercions=coercions
        )
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
                session_recovery_hint=lambda: (
                    GAP_FILL_HINT if primary else EXPLORATION_GAP_FILL_HINT
                ),
            )
        loop.run(prompt)
        after = {p.id: p for p in store.list_proof_attempts(rt.ot_dir, pid)}
        changed = sorted(
            p_id for p_id, p in after.items() if p_id not in before or before[p_id] != p.updated_at
        )
        # A non-primary branch's obligations come from the sketch *it* wrote. The gate
        # keeps proof_write off the primary, so a changed primary here means some other
        # route touched it — that is not this branch's progress and must not seed its
        # obligations from the proof branch's gaps.
        own = [p_id for p_id in changed if primary or after[p_id].scope == "exploration"]
        turns = max(1, loop.steps_run)
        decision_id = lease.decision.decision_id
        coercion_notes = (
            [
                f"{len(coercions)} proof_write call(s) rewritten to scope=exploration "
                f"(asked: {', '.join(coercions)}); a {ctx.root_relation.value} branch never "
                "writes the primary sketch"
            ]
            if coercions
            else []
        )
        if not own:
            return WorkerResult(
                status="failed",
                error_category="model_no_progress",
                message=f"no proof_write in {turns} model turn(s)",
                usage=CostTotals(steps=turns),
                routing_decision_id=decision_id,
                notes=[
                    f"{turns} turn(s), {loop.tool_calls_this_run} tool call(s), no proof_write",
                    *coercion_notes,
                ],
                failure_signature=build_failure_signature(
                    role=self.role,
                    strategy_class=strategy,
                    assumption_context=ctx.assumption_context,
                    tool_or_solver="proof_write",
                    error_category="model_no_progress",
                    counterargument=(
                        "only the primary sketch changed; a "
                        f"{ctx.root_relation.value} branch must write scope=exploration"
                        if changed
                        else (
                            "gap-fill turns produced no proof_write"
                            if prior
                            else "no proof_write and no bootstrap"
                        )
                    ),
                    verifier_backends=formal_backends(rt.config),
                ),
            )
        newest_id = max(own, key=lambda i: (after[i].updated_at, i))
        proof = after[newest_id]
        gaps = explicit_gaps(
            gaps=list(proof.gaps), body=_proof_body(rt.ot_dir, pid, proof.body_path)
        )
        known = {ob.statement.strip().lower() for ob in ctx.open_obligations}
        # A reworded gap is still the same obligation: dedup on (source proof, gap
        # marker) as well — a live refinement minted OBL-0004/0005 duplicating
        # OBL-0001/0002 for the same GAP-1/GAP-2 because only exact statement text
        # was compared, and the duplicates polluted every later worker prompt.
        known_markers = {
            (ob.source_proof_id, ob.gap_marker)
            for ob in ctx.open_obligations
            if ob.source_proof_id and ob.gap_marker
        }
        obligations: list[ObligationProposal] = []
        for n, gap in enumerate(gaps, start=1):
            marker = gap_marker_key(gap) or f"GAP-{n}"
            if gap.strip().lower() in known or (proof.id, marker) in known_markers:
                continue
            obligations.append(
                ObligationProposal(
                    statement=gap,
                    assumptions=list(ctx.assumption_context),
                    root_relation=ctx.root_relation,
                    closure_modes=list(GAP_CLOSURE_MODES),
                    source_proof_id=proof.id,
                    gap_marker=marker,
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
                for p_id in own
            ],
            obligations=obligations,
            usage=CostTotals(steps=turns),
            routing_decision_id=decision_id,
            notes=[
                f"{proof.id} ({proof.status}, scope {proof.scope}) with {len(gaps)} open gap(s); "
                f"{len(obligations)} new obligation(s) proposed",
                f"{turns} model turn(s), bootstrap used: {loop.bootstrap_used}",
                *coercion_notes,
            ],
        )


__all__ = [
    "EXPLORATION_GAP_FILL_HINT",
    "GAP_CLOSURE_MODES",
    "GAP_FILL_HINT",
    "MIN_BRIDGE_CHARS",
    "PRIMARY_RELATIONS",
    "ProverWorker",
    "bootstrap_args",
    "branch_instructions",
    "branch_objective",
    "connection_text",
    "scope_gate",
]
