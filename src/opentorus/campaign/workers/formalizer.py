"""The formalizer: formal-backend submissions, or an honest ``tool_unavailable``.

Formalization means a proof assistant or SMT solver (``lean4`` / ``coq`` / ``smt`` in
``tools.verifiers``); the pure-Python certificate checkers (``sympy``, ``interval``)
are not formalization targets. With no such backend enabled the worker fails at once
with a ``tool_unavailable`` signature that records the enabled backends — the
reactivation condition is "the verification stack changed", nothing else. With a
backend enabled but the mock provider there is no formal source to submit (the mock
writes none), so the work item fails ``verifier_inconclusive`` with the reason spelled
out. With a real provider and a backend, the model formalizes and calls
``proof_submit`` in a bounded loop; every new ledger entry is reported as an artifact
plus a verification, and a rejected submission is a ``verifier_rejected`` signature.
No path ever marks anything checked without an accepted backend run.
"""

from __future__ import annotations

from opentorus.campaign.failures import build_failure_signature
from opentorus.campaign.models import (
    ArtifactRef,
    CostTotals,
    ErrorCategory,
    VerificationRef,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import (
    WorkerRuntime,
    acquire_lease,
    bounded_loop,
    formal_backends,
    is_mock_provider,
)
from opentorus.errors import OpenTorusError


def _prompt(ctx: WorkerContext, backends: list[str]) -> str:
    return (
        f"Formalization attempt for {ctx.root_problem.problem_id} "
        f"(enabled backends: {', '.join(backends)}).\n"
        f"Statement: {ctx.root_problem.statement}\nBranch objective: {ctx.branch_objective}\n"
        "Formalize the definitions and the statement (or a fully closed lemma) and call "
        "proof_submit(backend=..., source=...). On REJECTED read the verifier output, fix "
        "the source and resubmit. Only an ACCEPTED submission is machine-checked."
    )


class FormalizerWorker:
    role = WorkerRole.formalizer

    def _failure(
        self,
        ctx: WorkerContext,
        *,
        category: ErrorCategory,
        counterargument: str,
        backends: list[str],
        artifacts: list[ArtifactRef] | None = None,
        artifact_ids: list[str] | None = None,
        steps: int = 1,
        decision_id: str | None = None,
        verifications: list[VerificationRef] | None = None,
    ) -> WorkerResult:
        return WorkerResult(
            status="failed",
            error_category=category,
            message=counterargument,
            artifacts_created=list(artifacts or []),
            usage=CostTotals(steps=steps),
            routing_decision_id=decision_id,
            notes=[counterargument],
            verifications=list(verifications or []),
            failure_signature=build_failure_signature(
                role=self.role,
                strategy_class=ctx.strategy_key or "formalization_attempt",
                assumption_context=ctx.assumption_context,
                tool_or_solver="formal:" + (",".join(backends) or "none"),
                error_category=category,
                counterargument=counterargument,
                artifact_ids=list(artifact_ids or []),
                verifier_backends=backends,
            ),
        )

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.research.verifiers.proofs import list_proofs

        backends = formal_backends(rt.config)
        if not backends:
            return self._failure(
                ctx,
                category="tool_unavailable",
                counterargument=(
                    "no formal proof-assistant/SMT backend enabled (tools.verifiers.lean/coq/smt "
                    "are off); formalization cannot run"
                ),
                backends=backends,
            )
        try:
            lease = acquire_lease(ctx, rt)
        except OpenTorusError as exc:
            return self._failure(
                ctx,
                category="tool_unavailable",
                counterargument=f"no eligible provider: {exc}",
                backends=backends,
            )
        decision_id = lease.decision.decision_id
        if is_mock_provider(lease.provider):
            return self._failure(
                ctx,
                category="verifier_inconclusive",
                counterargument=(
                    f"backend(s) {', '.join(backends)} enabled but no formal source available "
                    "for this objective (the mock provider writes none)"
                ),
                backends=backends,
                decision_id=decision_id,
            )
        before = {p.id for p in list_proofs(rt.ot_dir)}
        loop = bounded_loop(ctx, rt, lease=lease)
        loop.run(_prompt(ctx, backends))
        steps = max(1, loop.steps_run)
        proofs = sorted(
            (p for p in list_proofs(rt.ot_dir) if p.id not in before), key=lambda p: p.id
        )
        artifacts = [
            ArtifactRef(artifact_id=p.id, kind="proof", branch_id=ctx.branch_id) for p in proofs
        ]
        verifications = [
            VerificationRef(
                artifact_id=p.id,
                backend=p.backend,
                accepted=bool(p.accepted),
                inconclusive=bool(p.inconclusive),
            )
            for p in proofs
        ]
        accepted = [p for p in proofs if p.accepted and not p.inconclusive]
        if accepted:
            return WorkerResult(
                status="completed",
                artifacts_created=artifacts,
                verifications=verifications,
                usage=CostTotals(steps=steps),
                routing_decision_id=decision_id,
                notes=[f"{p.id}: {p.backend} accepted" for p in accepted],
            )
        if not proofs:
            return self._failure(
                ctx,
                category="verifier_inconclusive",
                counterargument=f"no proof_submit in {steps} model turn(s)",
                backends=backends,
                steps=steps,
                decision_id=decision_id,
            )
        inconclusive = all(p.inconclusive for p in proofs)
        outputs = "; ".join(f"{p.id}: {p.output.strip()[:120]}" for p in proofs)
        return self._failure(
            ctx,
            category="verifier_inconclusive" if inconclusive else "verifier_rejected",
            counterargument=(
                f"backend inconclusive ({outputs})"
                if inconclusive
                else f"backend REJECTED the submission(s) ({outputs})"
            ),
            backends=backends,
            artifacts=artifacts,
            artifact_ids=[p.id for p in proofs],
            steps=steps,
            decision_id=decision_id,
            verifications=verifications,
        )


__all__ = ["FormalizerWorker"]
