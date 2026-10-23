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

Formal proof-state continuation: when this branch's previous Lean/Coq candidate
failed, the next work item is told to *repair* it (its source and structured checker
feedback are in the prompt); every :data:`FRESH_ROOT_EVERY`-th attempt starts from the
root problem instead. A candidate refused only for ``sorry`` gets an automatic
tactic-suite pass (``verifiers.tactic_suite``) whose fully closed splice is re-verified
through the full gate. A claim's frozen formal statement, when one is accepted, is put
in the prompt verbatim.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from opentorus.research.verifiers.proofs import ProofAttempt


# Every N-th formal attempt on a branch starts from the root problem again instead of
# repairing the previous candidate (cf. open-math-harness ``pi_doubling``: keep repair
# continuations, but keep adding fresh root attempts so one bad skeleton cannot
# capture the branch).
FRESH_ROOT_EVERY = 4
_MAX_PREVIOUS_SOURCE = 6000
_PROOF_ASSISTANTS = ("lean4", "coq")


def _branch_formal_proofs(ctx: WorkerContext, ot_dir: Path) -> list[ProofAttempt]:
    """This branch's earlier Lean/Coq submissions (ids from ``branch_artifact_ids``)."""
    from opentorus.research.verifiers.proofs import list_proofs

    own = set(ctx.branch_artifact_ids)
    if not own:
        return []
    return sorted(
        (p for p in list_proofs(ot_dir) if p.id in own and p.backend in _PROOF_ASSISTANTS),
        key=lambda p: p.id,
    )


def continuation(ctx: WorkerContext, ot_dir: Path) -> tuple[str, ProofAttempt | None]:
    """``(mode, previous)``: ``root`` (nothing to continue), ``repair`` (the previous
    candidate failed — continue from it), or ``fresh_root`` (every
    :data:`FRESH_ROOT_EVERY`-th attempt, or after an accepted candidate)."""
    prior = _branch_formal_proofs(ctx, ot_dir)
    if not prior:
        return "root", None
    last = prior[-1]
    if last.accepted or not last.available:
        return "fresh_root", last
    if (len(prior) + 1) % FRESH_ROOT_EVERY == 0:
        return "fresh_root", last
    return "repair", last


def _repair_section(ot_dir: Path, previous: ProofAttempt) -> str:
    from opentorus.research.verifiers.diagnostics import render

    try:
        source = (ot_dir / previous.source_path).read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(source) > _MAX_PREVIOUS_SOURCE:
        source = source[:_MAX_PREVIOUS_SOURCE] + "\n-- … (truncated)"
    verdict = "inconclusive" if previous.inconclusive else "rejected"
    why = f" ({previous.rejection})" if previous.rejection else ""
    feedback = render(previous.diagnostics) or (previous.output or "").strip()[:1500]
    if previous.backend == "lean4" and previous.rejection == "sorry":
        from opentorus.research.verifiers.tactic_suite import hollow_sorries

        if hollow_sorries(source):
            feedback += (
                "\nHOLLOW: a `have` restates the theorem's goal and is closed by `sorry` — "
                "the whole proof is hiding in that gap; prove it, do not restate it."
            )
    return (
        f"\nREPAIR FIRST: this branch's previous candidate {previous.id} was {verdict}{why} "
        f"by {previous.backend}. Continue from it — keep what elaborates and fix the first "
        "error — rather than starting over:\n"
        f"```\n{source}\n```\nStructured checker feedback:\n{feedback}\n"
    )


def _statement_section(ctx: WorkerContext, ot_dir: Path) -> str:
    from opentorus.research.verifiers.statements import active_statement, statement_source

    for backend in _PROOF_ASSISTANTS:
        stmt = active_statement(
            ot_dir,
            ctx.target_claim_id,
            backend,
            submitted_under=ctx.root_problem.problem_id,
        )
        if stmt is None:
            continue
        try:
            frozen = statement_source(ot_dir, stmt)
        except OSError:
            continue
        return (
            f"\n{ctx.target_claim_id} has a human-accepted frozen formal statement "
            f"{stmt.id} ({stmt.backend}). A proof verifies the claim only if your file "
            "begins with its preamble unchanged, contains its statement verbatim, and is "
            f"submitted with claim_id={ctx.target_claim_id}. Replace only the `sorry`:\n"
            f"```\n{frozen}\n```\n"
        )
    return ""


def _prompt(
    ctx: WorkerContext,
    backends: list[str],
    *,
    ot_dir: Path | None = None,
    mode: str = "root",
    previous: ProofAttempt | None = None,
) -> str:
    text = (
        f"Formalization attempt for {ctx.root_problem.problem_id} "
        f"(enabled backends: {', '.join(backends)}).\n"
        f"Statement: {ctx.root_problem.statement}\nBranch objective: {ctx.branch_objective}\n"
        "Formalize the definitions and the statement (or a fully closed lemma) and call "
        "proof_submit(backend=..., source=...). On REJECTED read the verifier output, fix "
        "the source and resubmit. Only an ACCEPTED submission is machine-checked."
    )
    if ot_dir is None:
        return text
    text += _statement_section(ctx, ot_dir)
    if mode == "repair" and previous is not None:
        text += _repair_section(ot_dir, previous)
    elif mode == "fresh_root" and previous is not None:
        text += (
            f"\nFRESH ROOT ATTEMPT: start again from the problem statement; do not patch "
            f"{previous.id}. A different formalization or proof route is the point."
        )
    return text


def tactic_suite_pass(rt: WorkerRuntime, proofs: list[ProofAttempt]) -> list[ProofAttempt]:
    """Try the fixed tactic suite on the latest candidate refused only for ``sorry``.

    Re-submits a fully closed splice through :func:`submit_proof` — the full gate
    (sorry/axiom/statement checks) decides; nothing is accepted here. Returns the new
    attempts (empty when the pass did not apply or closed nothing).
    """
    from opentorus.research.verifiers.backends import Lean4Backend
    from opentorus.research.verifiers.proofs import submit_proof
    from opentorus.research.verifiers.registry import get_verifier
    from opentorus.research.verifiers.tactic_suite import run_suite

    if not getattr(rt.config.tools.verifiers, "lean_tactic_suite", False):
        return []
    candidates = [
        p for p in proofs if p.backend == "lean4" and not p.accepted and p.rejection == "sorry"
    ]
    if not candidates:
        return []
    target = candidates[-1]
    verifier = get_verifier(rt.config, "lean4")
    if not isinstance(verifier, Lean4Backend) or not verifier.is_available():
        return []
    try:
        source = (rt.ot_dir / target.source_path).read_text(encoding="utf-8")
    except OSError:
        return []
    suite = run_suite(verifier, source)
    if suite.spliced is None:
        return []
    attempt = submit_proof(
        rt.ot_dir,
        rt.config,
        "lean4",
        suite.spliced,
        claim_id=target.claim_id,
        problem_id=target.problem_id,
        submitted_under=target.submitted_under,
        verifier=verifier,
    )
    return [attempt]


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
        mode, previous = continuation(ctx, rt.ot_dir)
        loop = bounded_loop(ctx, rt, lease=lease)
        loop.run(_prompt(ctx, backends, ot_dir=rt.ot_dir, mode=mode, previous=previous))
        steps = max(1, loop.steps_run)
        proofs = sorted(
            (p for p in list_proofs(rt.ot_dir) if p.id not in before), key=lambda p: p.id
        )
        if not any(p.accepted for p in proofs):
            proofs += tactic_suite_pass(rt, proofs)
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
