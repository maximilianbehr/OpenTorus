"""Proof attempts as provenance-rich artifacts.

Each submission of a formal goal/term to a backend produces a ``PROOF-*``
artifact: the exact source, the backend + version, and the verbatim
accept/reject output. Accepted proofs that target a claim add a ``validates``
edge to the artifact graph (rendered in the M35 graph view).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_id, read_jsonl

if TYPE_CHECKING:
    from opentorus.config import Config
    from opentorus.research.verifiers.base import VerificationResult, Verifier
    from opentorus.research.verifiers.statements import FormalStatement

_SUFFIX = {
    "lean4": ".lean",
    "lean": ".lean",
    "coq": ".v",
    "smt": ".smt2",
    "z3": ".smt2",
    "sympy": ".json",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProofAttempt(BaseModel):
    """A recorded formal-verification attempt."""

    id: str
    backend: str
    backend_version: str | None = None
    accepted: bool
    available: bool = True
    # Timeout/crash/parse failure: the checker gave up — distinct from a genuine
    # rejection, so "the tool gave up" is never read as "the proof is wrong".
    inconclusive: bool = False
    outcome: str | None = None  # SMT: "unsat" | "sat" | "unknown"
    claim_id: str | None = None
    # Which dossier ``claim_id`` belongs to; ``None`` means the workspace claim ladder.
    # The two stores share the ``CLAIM-NNNN`` id space while proofs.jsonl is
    # workspace-global, so an unqualified id is ambiguous: one real workspace held a
    # dossier CLAIM-0001 ("for every bipartite graph H …") and a workspace CLAIM-0001
    # ("for the 4-vertex block graph …") at once. Without this field a proof of the
    # instance answers a lookup for the general statement.
    problem_id: str | None = None
    # Which campaign produced this submission. Distinct from ``problem_id`` above, and
    # deliberately so: that one answers "which claim store does claim_id belong to"
    # (identity), this one answers "was anything machine-checked while working on this
    # dossier" (provenance). Collapsing the two into one field is what made the id
    # collision possible in the first place, and an attempt to reuse ``problem_id`` for
    # the second question blocked the campaign gate outright — every agent submission
    # targets a workspace claim and so carries no ``problem_id`` at all.
    submitted_under: str | None = None
    source_path: str
    output: str = ""
    # Digest of the exact source submitted. Lets an identical resubmission be answered
    # from the ledger instead of re-running the backend. ``None`` on records written
    # before this field existed; those simply never match.
    source_sha256: str | None = None
    # True when this record answers a resubmission of source already checked, rather
    # than a fresh backend run. Recorded so the artifact never overstates what ran.
    cached: bool = False
    # Proof-assistant gate outcome (Lean/Coq): why the gate refused (see
    # ``VerificationResult.rejection``), the axioms the theorem depends on, and the
    # audited theorem name.
    rejection: str | None = None
    axioms: list[str] | None = None
    theorem: str | None = None
    # Statement fidelity: the FSTMT-* frozen statement this source was checked
    # against (and its digest at the time). ``statement_bound`` is True only when the
    # checker confirmed the verbatim statement *and* the elaborated type. A Lean/Coq
    # proof that is not statement-bound never promotes a claim — it is support.
    statement_id: str | None = None
    statement_sha256: str | None = None
    statement_bound: bool = False
    confined: bool | None = None
    # Structured checker feedback (``diagnostics.summarize``); raw output above.
    diagnostics: dict | None = None
    created_at: datetime = Field(default_factory=_utcnow)


def can_promote(proof: ProofAttempt) -> tuple[bool, str]:
    """Whether ``proof`` may promote its claim, and why not if it may not.

    An accepted, conclusive attempt promotes — except that a proof-assistant result
    (Lean/Coq) must also be *statement-bound*: checked against a human-accepted frozen
    formal statement of that claim. Otherwise any accepted file could be cited for any
    claim; the checker only says *some* theorem was proved.
    """
    from opentorus.research.verifiers.statements import PROOF_ASSISTANT_BACKENDS

    if not proof.accepted:
        return False, f"{proof.id}: {proof.backend} did not accept this attempt"
    if proof.inconclusive:
        return False, f"{proof.id}: {proof.backend} was inconclusive"
    if proof.backend in PROOF_ASSISTANT_BACKENDS and not proof.statement_bound:
        return False, (
            f"{proof.id}: an accepted {proof.backend} proof that is not bound to a "
            "human-accepted frozen formal statement (FSTMT-*) of the claim. It shows "
            "that *some* theorem was proved, not that this claim was; it counts as "
            "support. Freeze the statement (`opentorus proof statement add` + "
            "`accept`) and resubmit against it"
        )
    return True, ""


def _cached_resubmission(ot_dir: Path, prior: ProofAttempt, claim_id: str | None) -> ProofAttempt:
    """Answer a byte-identical resubmission from the ledger.

    The prior attempt is returned as-is rather than duplicated, with its output prefixed
    so neither the model nor the reader can mistake this for a second, independent
    check. Resubmitting unchanged source is also a signal in its own right — the model
    is circling — so the message says so.
    """
    verdict = "ACCEPTED" if prior.accepted else "REJECTED"
    note = (
        f"[identical source already checked: {prior.id} — {prior.backend} {verdict}. "
        "Not re-run, and no second artifact recorded. Resubmitting unchanged source "
        "cannot change the verdict; change the proof, or treat this as settled.]\n\n"
    )
    echoed = prior.model_copy(update={"output": note + prior.output, "cached": True})
    # An accepted proof newly pointed at a claim still earns its graph edge.
    if prior.accepted and claim_id and claim_id != prior.claim_id:
        from opentorus.research.graph import add_edge

        add_edge(
            ot_dir,
            prior.id,
            claim_id,
            "validates",
            rationale=f"Formally accepted by {prior.backend} (identical source, {prior.id})",
        )
    return echoed


def _verify_against_statement(
    ot_dir: Path, verifier: Verifier, source: str, statement: FormalStatement
) -> VerificationResult:
    """Check ``source`` against a frozen statement (verbatim + elaborated type).

    The statement's pristine type is computed once per checker version and cached on
    the FSTMT record. A verifier without the statement-fidelity protocol (a test stub,
    an SMT backend) cannot bind: its result is returned as-is, unbound.
    """
    from opentorus.research.verifiers.backends import FrozenSpec
    from opentorus.research.verifiers.base import VerificationResult
    from opentorus.research.verifiers.statements import (
        record_pristine_type,
        statement_source,
    )

    verify_against = getattr(verifier, "verify_against", None)
    compute_pristine = getattr(verifier, "pristine_type", None)
    if verify_against is None or compute_pristine is None:
        return verifier.verify(source)
    name = getattr(verifier, "name", statement.backend)
    if not verifier.is_available():
        return VerificationResult(
            backend=name,
            accepted=False,
            available=False,
            output=f"Backend '{name}' is not installed; formal verification unavailable.",
        )
    frozen = statement_source(ot_dir, statement)
    version = verifier.version()
    pristine = statement.pristine_type
    if pristine is None or statement.pristine_backend_version != version:
        pristine, detail = compute_pristine(frozen)
        if pristine is None:
            return VerificationResult(
                backend=name,
                backend_version=version,
                accepted=False,
                inconclusive=True,
                rejection="frozen_statement_invalid",
                output=(
                    f"[opentorus gate] the frozen statement {statement.id} could not be "
                    f"elaborated, so nothing can be checked against it (inconclusive, "
                    f"not a verdict on this proof):\n{detail}"
                ),
            )
        record_pristine_type(ot_dir, statement.id, pristine, version)
    spec = FrozenSpec(source=frozen, theorem=statement.theorem, pristine_type=pristine)
    return verify_against(source, spec)


def proofs_dir(ot_dir: Path) -> Path:
    return ot_dir / "proofs"


def proofs_path(ot_dir: Path) -> Path:
    return ot_dir / "proofs.jsonl"


def list_proofs(ot_dir: Path) -> list[ProofAttempt]:
    return read_jsonl(proofs_path(ot_dir), ProofAttempt)


def get_proof(ot_dir: Path, proof_id: str) -> ProofAttempt | None:
    for proof in list_proofs(ot_dir):
        if proof.id == proof_id:
            return proof
    return None


def accepted_proof_for_claim(
    ot_dir: Path, claim_id: str, problem_id: str | None = None
) -> ProofAttempt | None:
    """Most recent *promoting* attempt for a claim in its own namespace, if any.

    Promoting means :func:`can_promote`: accepted, conclusive and — for Lean/Coq —
    bound to the claim's frozen formal statement.

    ``problem_id=None`` asks about a workspace claim and therefore ignores attempts
    recorded against a dossier claim of the same id, and vice versa. Matching on the
    bare id alone let a proof of a concrete instance satisfy a lookup for the general
    conjecture that happened to share its number.
    """
    matches = [
        p
        for p in list_proofs(ot_dir)
        if p.claim_id == claim_id and can_promote(p)[0] and p.problem_id == problem_id
    ]
    return matches[-1] if matches else None


def submit_proof(
    ot_dir: Path,
    config: Config,
    backend: str,
    source: str,
    *,
    claim_id: str | None = None,
    problem_id: str | None = None,
    submitted_under: str | None = None,
    verifier: Verifier | None = None,
    timeout: int | None = None,
) -> ProofAttempt:
    """Submit ``source`` to a formal backend and persist the attempt.

    If ``verifier`` is given it is used directly (for tests/injection); otherwise
    the backend is resolved from ``config``. An unconfigured backend raises rather
    than faking rigor. Accepted attempts targeting a claim add a ``validates``
    edge to the graph.
    """
    if verifier is None:
        from opentorus.research.verifiers.registry import get_verifier

        verifier = get_verifier(config, backend, timeout=timeout)
    if verifier is None:
        raise OpenTorusError(
            f"Verifier '{backend}' is not enabled. Enable it via "
            "config.tools.verifiers; with no backend, formal verification is unavailable."
        )

    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    from opentorus.research.verifiers.statements import (
        PROOF_ASSISTANT_BACKENDS,
        active_statement,
    )

    statement = None
    family = getattr(verifier, "name", backend)
    if claim_id and (family in PROOF_ASSISTANT_BACKENDS or backend in PROOF_ASSISTANT_BACKENDS):
        statement = active_statement(
            ot_dir,
            claim_id,
            "coq" if "coq" in (family, backend) else "lean4",
            problem_id=problem_id,
            submitted_under=submitted_under,
        )
    statement_sha = statement.sha256 if statement is not None else None
    existing = list_proofs(ot_dir)
    # An identical source gets an identical verdict, so re-running the backend buys
    # nothing — and on Lean/Coq that is minutes per submission. Inconclusive results are
    # deliberately excluded: a timeout or a crash says nothing about the mathematics, so
    # it is worth trying again. Experiments have had a content-addressed cache all
    # along; verification did not.
    for prior in reversed(existing):
        if (
            prior.source_sha256 == digest
            and prior.backend == getattr(verifier, "name", backend)
            and not prior.inconclusive
            and prior.available
            and prior.problem_id == problem_id
            and prior.statement_sha256 == statement_sha
        ):
            return _cached_resubmission(ot_dir, prior, claim_id)

    if statement is not None:
        result = _verify_against_statement(ot_dir, verifier, source, statement)
    else:
        result = verifier.verify(source)

    existing = list_proofs(ot_dir)
    # The PROOF-NNNN prefix is shared with dossier proof attempts — mint across both
    # so a backend submission never reuses the id of an NL sketch (or vice versa).
    from opentorus.research.dossier.store import all_dossier_proof_ids

    proof_id = next_id("PROOF", [*(p.id for p in existing), *all_dossier_proof_ids(ot_dir)])
    pdir = proofs_dir(ot_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    suffix = _SUFFIX.get(result.backend, _SUFFIX.get(backend, ".txt"))
    source_file = pdir / f"{proof_id}{suffix}"
    source_file.write_text(source, encoding="utf-8")
    rel_source = f"proofs/{source_file.name}"

    attempt = ProofAttempt(
        id=proof_id,
        backend=result.backend,
        backend_version=result.backend_version,
        accepted=result.accepted,
        available=result.available,
        inconclusive=result.inconclusive,
        outcome=result.outcome,
        claim_id=claim_id,
        problem_id=problem_id,
        submitted_under=submitted_under,
        source_path=rel_source,
        output=result.output,
        source_sha256=digest,
        rejection=result.rejection,
        axioms=result.axioms,
        theorem=result.theorem,
        statement_id=statement.id if statement is not None else None,
        statement_sha256=statement_sha,
        statement_bound=bool(result.statement_bound and statement is not None),
        confined=result.confined,
        diagnostics=result.diagnostics,
    )
    append_jsonl(proofs_path(ot_dir), attempt)

    if attempt.accepted and claim_id:
        from opentorus.research.graph import add_edge

        version = f" {result.backend_version}" if result.backend_version else ""
        promotes, why_not = can_promote(attempt)
        if not promotes and not attempt.inconclusive:
            add_edge(
                ot_dir,
                proof_id,
                claim_id,
                "supports",
                rationale=(
                    f"Accepted by {result.backend}{version}, but not bound to a frozen "
                    "formal statement of the claim: it proves some theorem, not "
                    "necessarily this claim."
                ),
            )
        elif result.general is False:
            # A closed arithmetic fact checks one instance, so it *supports* the claim
            # it is filed under — it does not validate it. Real runs submitted "1+2 = 3"
            # against "for n=3, max A >= 4", and "2**(4-2) + 1 = 5" against the Happy
            # Ending conjecture, and each was recorded as validating the claim. Seven of
            # eleven accepted proofs in one sweep were of that shape. Claim *status* was
            # never promoted — that invariant held — but the graph asserted a
            # relationship the artifact does not carry.
            add_edge(
                ot_dir,
                proof_id,
                claim_id,
                "supports",
                rationale=(
                    f"Accepted by {result.backend}{version}, but the certificate is a "
                    "closed arithmetic statement: it verifies this instance, not the "
                    "claim in general."
                ),
            )
        else:
            add_edge(
                ot_dir,
                proof_id,
                claim_id,
                "validates",
                rationale=f"Formally accepted by {result.backend}{version}",
            )

    # An SMT ``sat`` verdict is a *candidate* refutation: the model may be spurious
    # if the goal was mis-encoded. Until it is round-trip-validated against the
    # un-negated goal, record it as WEAK, explicitly unvalidated, contradicting
    # evidence — never strong enough to refute a claim on its own. ``unknown`` is
    # inconclusive and records nothing.
    if not attempt.accepted and result.outcome == "sat" and result.model and claim_id:
        from opentorus.research.dossier.store import get_active_problem
        from opentorus.research.evidence import add_evidence
        from opentorus.research.graph import add_edge

        add_evidence(
            ot_dir,
            claim_id,
            source_type="external",
            source_id=proof_id,
            summary=(
                f"{result.backend} returned a candidate counterexample model "
                "(UNVALIDATED — not round-tripped against the un-negated goal; a "
                f"mis-encoded goal can yield a spurious model):\n{result.model}"
            ),
            direction="contradicts",
            strength="weak",
            problem_id=get_active_problem(ot_dir),
        )
        add_edge(
            ot_dir,
            proof_id,
            claim_id,
            "contradicts",
            rationale=f"{result.backend} returned sat (counterexample model).",
        )

    return attempt
