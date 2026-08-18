"""The verifier-coordinator: proposes obligation closures — only ones an artifact backs.

The coordinator never verifies anything itself and never touches a claim status. It
looks at each open obligation's cited artifacts and asks, per closure mode, whether
an *accepted* artifact of the required class exists:

* ``formal_proof`` / ``smt_certificate`` / ``exact_symbolic_certificate`` /
  ``validated_numerical_certificate``: a ``PROOF-*`` in the workspace ledger passing the
  same four checks as ``dossier.claims._require_verification_artifact`` — exists, not
  inconclusive, accepted, recorded under this problem (or unscoped). ``formal_proof``
  accepts any backend-checked artifact (that is the codebase's meaning of
  verification-grade); the certificate modes additionally require the matching backend.
* ``accepted_counterexample_certificate``: a cited dossier claim of type
  ``COUNTEREXAMPLE_VERIFIED`` (creatable only with an explicit verification record).
* ``nl_proof_referee_accepted``: the cited primary proof attempt has no open gaps and
  the hostile referee (``referee_review(persist=False)``) passes the dossier.
* ``accepted_literature_theorem``: a cited ``THMREF-`` that a human accepted, with a
  recorded applicability check whose result is ``accepted`` for this problem.

Anything else stays open with a note. With no obligations the coordinator completes
with an empty proposal list.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.models import (
    ClosureMode,
    ClosureProposal,
    CostTotals,
    Obligation,
    ObligationStatus,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import WorkerRuntime

_BACKEND_MODES: dict[str, ClosureMode] = {
    "lean4": ClosureMode.formal_proof,
    "lean": ClosureMode.formal_proof,
    "coq": ClosureMode.formal_proof,
    "smt": ClosureMode.smt_certificate,
    "z3": ClosureMode.smt_certificate,
    "cvc5": ClosureMode.smt_certificate,
    "sympy": ClosureMode.exact_symbolic_certificate,
    "symbolic": ClosureMode.exact_symbolic_certificate,
    "interval": ClosureMode.validated_numerical_certificate,
    "validated_numerical": ClosureMode.validated_numerical_certificate,
}
_PROOF_MODES: frozenset[ClosureMode] = frozenset(
    {
        ClosureMode.formal_proof,
        ClosureMode.smt_certificate,
        ClosureMode.exact_symbolic_certificate,
        ClosureMode.validated_numerical_certificate,
    }
)


def _cited(ob: Obligation) -> list[str]:
    seen: list[str] = []
    for aid in [*ob.supporting_artifacts, *([ob.source_proof_id] if ob.source_proof_id else [])]:
        key = aid.strip().upper()
        if key and key not in seen:
            seen.append(key)
    return seen


def _proof_verdict(ot_dir: Path, problem_id: str, proof_id: str) -> tuple[bool, str, str]:
    """``(accepted, backend, reason)`` with the four checks of the dossier claim gate."""
    from opentorus.research.verifiers.proofs import get_proof

    proof = get_proof(ot_dir, proof_id)
    if proof is None:
        return False, "", f"{proof_id}: no such attempt in the proof ledger"
    if proof.inconclusive:
        return False, proof.backend, f"{proof_id}: {proof.backend} was inconclusive"
    if not proof.accepted:
        return False, proof.backend, f"{proof_id}: {proof.backend} REJECTED this attempt"
    if proof.problem_id is not None and proof.problem_id != problem_id:
        return False, proof.backend, f"{proof_id}: recorded under {proof.problem_id}"
    return True, proof.backend, f"{proof_id}: {proof.backend} accepted"


def _proof_closure(
    ot_dir: Path, problem_id: str, ob: Obligation, notes: list[str]
) -> ClosureProposal | None:
    wanted = [m for m in ob.closure_modes if m in _PROOF_MODES]
    if not wanted:
        return None
    for aid in _cited(ob):
        if not aid.startswith("PROOF-"):
            continue
        ok, backend, reason = _proof_verdict(ot_dir, problem_id, aid)
        notes.append(reason)
        if not ok:
            continue
        backend_mode = _BACKEND_MODES.get(backend.lower())
        # Prefer the specific certificate mode when the obligation lists it and the
        # backend matches; otherwise the generic machine-checked mode.
        if backend_mode is not None and backend_mode in wanted:
            mode = backend_mode
        elif ClosureMode.formal_proof in wanted:
            mode = ClosureMode.formal_proof
        else:
            notes.append(f"{aid}: backend {backend} does not match {[m.value for m in wanted]}")
            continue
        return ClosureProposal(
            obligation_id=ob.obligation_id,
            artifact_id=aid,
            mode=mode,
            check_id=aid,
            verdict=reason,
        )
    return None


def _counterexample_closure(
    ot_dir: Path, problem_id: str, ob: Obligation, notes: list[str]
) -> ClosureProposal | None:
    if ClosureMode.accepted_counterexample_certificate not in ob.closure_modes:
        return None
    from opentorus.research.dossier import store

    claims = {c.id: c for c in store.list_claims(ot_dir, problem_id)}
    for aid in _cited(ob):
        claim = claims.get(aid)
        if claim is None:
            continue
        if claim.type == "COUNTEREXAMPLE_VERIFIED":
            return ClosureProposal(
                obligation_id=ob.obligation_id,
                artifact_id=aid,
                mode=ClosureMode.accepted_counterexample_certificate,
                check_id=aid,
                verdict=f"{aid} is COUNTEREXAMPLE_VERIFIED",
            )
        notes.append(f"{aid}: {claim.type} is not a verified counterexample")
    return None


def _referee_closure(
    ot_dir: Path, problem_id: str, ob: Obligation, notes: list[str]
) -> ClosureProposal | None:
    if ClosureMode.nl_proof_referee_accepted not in ob.closure_modes:
        return None
    from opentorus.research.dossier import store
    from opentorus.research.dossier.nl_proof import explicit_gaps

    cited = _cited(ob)
    proofs = [p for p in store.list_proof_attempts(ot_dir, problem_id) if p.id in cited]
    for proof in proofs:
        body = ""
        if proof.body_path:
            path = ot_dir / proof.body_path
            if path.is_file():
                body = path.read_text(encoding="utf-8")
        if explicit_gaps(gaps=list(proof.gaps), body=body):
            notes.append(f"{proof.id}: open gaps remain")
            continue
        try:
            from opentorus.research.dossier.referee import referee_review

            report = referee_review(ot_dir, problem_id, persist=False)
        except Exception as exc:  # noqa: BLE001 - the referee must never break a run
            notes.append(f"{proof.id}: referee unavailable ({exc})")
            continue
        if report.verdict == "pass":
            return ClosureProposal(
                obligation_id=ob.obligation_id,
                artifact_id=proof.id,
                mode=ClosureMode.nl_proof_referee_accepted,
                check_id=report.id or "referee",
                verdict="referee pass on a gap-free proof",
            )
        notes.append(f"{proof.id}: referee verdict {report.verdict}")
    return None


def _literature_closure(
    ot_dir: Path, problem_id: str, ob: Obligation, notes: list[str]
) -> ClosureProposal | None:
    if ClosureMode.accepted_literature_theorem not in ob.closure_modes:
        return None
    from opentorus.research.theorems import store as thm_store

    for aid in _cited(ob):
        if not aid.startswith("THMREF-"):
            continue
        ref = thm_store.get_reference(ot_dir, aid)
        if ref is None:
            notes.append(f"{aid}: no such theorem reference")
            continue
        if ref.review_status != "accepted":
            notes.append(f"{aid}: review status {ref.review_status} (needs accepted)")
            continue
        checks = [
            c
            for c in thm_store.list_applicability_checks(ot_dir, ref_id=aid)
            if c.problem_id.upper() == problem_id and str(c.result) == "accepted"
        ]
        if not checks:
            notes.append(f"{aid}: no accepted applicability check for {problem_id}")
            continue
        return ClosureProposal(
            obligation_id=ob.obligation_id,
            artifact_id=aid,
            mode=ClosureMode.accepted_literature_theorem,
            check_id=checks[-1].id or None,
            verdict="accepted reference with accepted applicability check",
        )
    return None


def closure_candidates(
    ot_dir: Path, problem_id: str, obligations: list[Obligation]
) -> tuple[list[ClosureProposal], list[str]]:
    """Closure proposals for the open obligations that an accepted artifact backs."""
    pid = problem_id.strip().upper()
    proposals: list[ClosureProposal] = []
    notes: list[str] = []
    for ob in obligations:
        if ob.status is not ObligationStatus.open and ob.status is not ObligationStatus.in_progress:
            continue
        proposal = (
            _proof_closure(ot_dir, pid, ob, notes)
            or _counterexample_closure(ot_dir, pid, ob, notes)
            or _referee_closure(ot_dir, pid, ob, notes)
            or _literature_closure(ot_dir, pid, ob, notes)
        )
        if proposal is not None:
            proposals.append(proposal)
        else:
            notes.append(f"{ob.obligation_id}: stays open (no accepted artifact backs a closure)")
    return proposals, notes


class VerifierCoordinatorWorker:
    role = WorkerRole.verifier_coordinator

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        proposals, notes = closure_candidates(
            rt.ot_dir, ctx.root_problem.problem_id, list(ctx.open_obligations)
        )
        return WorkerResult(
            status="completed",
            closure_proposals=proposals,
            notes=notes or ["no open obligations"],
            usage=CostTotals(),
        )


__all__ = ["VerifierCoordinatorWorker", "closure_candidates"]
