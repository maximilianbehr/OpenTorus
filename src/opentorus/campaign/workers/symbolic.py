"""The symbolic experimenter: exact certificates checked by the sympy backend.

A symbolic branch settles something only through an *exact* certificate the sympy
verifier accepts (``verifiers.proofs.submit_proof(backend="sympy")`` — the same
ledger the dossier claim gate reads). The certificate is a small JSON object
(``{"lhs": ..., "rhs": ..., "relation": "eq", "vars": {...}}``); the worker looks for
one after a ``certificate:`` marker in the branch objective (a human or the strategist
can put it there), or lets a real provider produce and submit one in a bounded loop.

Offline (mock provider) with no certificate in the objective the worker records an
honest ``verifier_inconclusive`` failure signature ("no symbolic certificate available
for this objective") — it never fabricates an identity to check. A rejected
certificate is ``verifier_rejected``; an inconclusive backend run is
``verifier_inconclusive``; an accepted one is a completed work item whose ``PROOF-*``
artifact and verification are reported for the campaign log.
"""

from __future__ import annotations

import json
import re

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
    is_mock_provider,
)
from opentorus.errors import OpenTorusError

CERTIFICATE_MARKER = re.compile(r"certificate\s*:\s*(\{.*\})", re.IGNORECASE | re.DOTALL)
NO_CERTIFICATE = "no symbolic certificate available for this objective"


def certificate_from_objective(objective: str) -> str | None:
    """The JSON certificate after a ``certificate:`` marker, if it parses."""
    match = CERTIFICATE_MARKER.search(objective or "")
    if not match:
        return None
    text = match.group(1).strip()
    # Take the shortest balanced prefix that parses (the objective may continue).
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[: i + 1]
                try:
                    json.loads(candidate)
                except json.JSONDecodeError:
                    return None
                return candidate
    return None


def _prompt(ctx: WorkerContext) -> str:
    return (
        f"Symbolic reformulation for {ctx.root_problem.problem_id}.\n"
        f"Statement: {ctx.root_problem.statement}\nBranch objective: {ctx.branch_objective}\n"
        "If a step of the argument is an exact identity or inequality, submit it as a JSON "
        'certificate {"lhs": ..., "rhs": ..., "relation": "eq|le|lt|ge|gt|ne", '
        '"vars": {"x": "real"}} via proof_submit(backend="sympy", source=<json>). Only an '
        "ACCEPTED submission is machine-checked; record anything else as an open gap."
    )


class SymbolicWorker:
    role = WorkerRole.symbolic_experimenter

    def _failure(
        self,
        ctx: WorkerContext,
        *,
        category: ErrorCategory,
        counterargument: str,
        artifacts: list[ArtifactRef],
        artifact_ids: list[str],
        steps: int,
        decision_id: str | None,
        verifications: list[VerificationRef] | None = None,
    ) -> WorkerResult:
        return WorkerResult(
            status="failed",
            error_category=category,
            message=counterargument,
            artifacts_created=artifacts,
            usage=CostTotals(steps=steps),
            routing_decision_id=decision_id,
            notes=[counterargument],
            verifications=list(verifications or []),
            failure_signature=build_failure_signature(
                role=self.role,
                strategy_class=ctx.strategy_key or "symbolic_simplification",
                assumption_context=ctx.assumption_context,
                tool_or_solver="sympy",
                error_category=category,
                counterargument=counterargument,
                artifact_ids=artifact_ids,
                verifier_backends=["sympy"],
            ),
        )

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.research.verifiers.proofs import list_proofs, submit_proof

        pid = ctx.root_problem.problem_id
        try:
            lease = acquire_lease(ctx, rt)
        except OpenTorusError as exc:
            return WorkerResult(
                status="failed",
                error_category="tool_unavailable",
                message=f"no eligible provider: {exc}",
                usage=CostTotals(steps=1),
            )
        decision_id = lease.decision.decision_id
        certificate = certificate_from_objective(ctx.branch_objective)
        turns = 0
        new_ids: list[str] = []
        if certificate is not None:
            try:
                attempt = submit_proof(
                    rt.ot_dir,
                    rt.config,
                    "sympy",
                    certificate,
                    problem_id=pid,
                    submitted_under=ctx.campaign_id,
                )
            except OpenTorusError as exc:
                return self._failure(
                    ctx,
                    category="tool_unavailable",
                    counterargument=f"sympy backend unavailable: {exc}",
                    artifacts=[],
                    artifact_ids=[],
                    steps=1,
                    decision_id=decision_id,
                )
            new_ids = [attempt.id]
        elif is_mock_provider(lease.provider):
            return self._failure(
                ctx,
                category="verifier_inconclusive",
                counterargument=NO_CERTIFICATE,
                artifacts=[],
                artifact_ids=[],
                steps=1,
                decision_id=decision_id,
            )
        else:
            before = {p.id for p in list_proofs(rt.ot_dir)}
            loop = bounded_loop(ctx, rt, lease=lease)
            loop.run(_prompt(ctx))
            turns = loop.steps_run
            new_ids = sorted(p.id for p in list_proofs(rt.ot_dir) if p.id not in before)
        steps = max(1, turns)
        proofs = {p.id: p for p in list_proofs(rt.ot_dir) if p.id in new_ids}
        artifacts = [
            ArtifactRef(artifact_id=pid_, kind="proof", branch_id=ctx.branch_id)
            for pid_ in sorted(proofs)
        ]
        verifications = [
            VerificationRef(
                artifact_id=p.id,
                backend=p.backend,
                accepted=bool(p.accepted),
                inconclusive=bool(p.inconclusive),
            )
            for p in sorted(proofs.values(), key=lambda p: p.id)
        ]
        accepted = [p for p in proofs.values() if p.accepted and not p.inconclusive]
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
                counterargument=(
                    NO_CERTIFICATE
                    if turns == 0
                    else f"no sympy certificate submitted in {turns} model turn(s)"
                ),
                artifacts=artifacts,
                artifact_ids=[],
                steps=steps,
                decision_id=decision_id,
            )
        inconclusive = all(p.inconclusive for p in proofs.values())
        outputs = "; ".join(f"{p.id}: {p.output.strip()[:120]}" for p in proofs.values())
        return self._failure(
            ctx,
            category="verifier_inconclusive" if inconclusive else "verifier_rejected",
            counterargument=(
                f"sympy could not settle the certificate ({outputs})"
                if inconclusive
                else f"sympy REJECTED the certificate ({outputs})"
            ),
            artifacts=artifacts,
            artifact_ids=sorted(proofs),
            steps=steps,
            decision_id=decision_id,
            verifications=verifications,
        )


__all__ = ["CERTIFICATE_MARKER", "NO_CERTIFICATE", "SymbolicWorker", "certificate_from_objective"]
