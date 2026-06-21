"""High-level claim / evidence / proof operations for a dossier.

This is where the epistemic discipline is applied. Adding evidence never
verifies a claim; only an explicit verification step (a verified proof attempt
or a recorded formal-proof artifact) can move a claim to a verified status.
"""

from __future__ import annotations

import re
from pathlib import Path

from opentorus.errors import OpenTorusError
from opentorus.research.dossier import store
from opentorus.research.dossier.models import (
    ClaimRecord,
    ClaimStatus,
    ClaimStatusChange,
    ClaimType,
    EvidenceDirection,
    EvidenceRecord,
    EvidenceType,
    ProofAttempt,
    utcnow,
)
from opentorus.research.dossier.validation import (
    assert_can_create_claim,
    assert_can_set_status,
    default_status_for_type,
    evidence_can_verify,
)

_EXP_ID_RE = re.compile(r"^EXP-\d+$")


def _log_status_change(
    ot_dir: Path,
    problem_id: str,
    claim_id: str,
    from_status: str,
    to_status: str,
    *,
    reason: str = "",
    artifact: str | None = None,
) -> None:
    """Append an epistemic-status transition to the dossier changelog (no-op if unchanged)."""
    if from_status == to_status:
        return
    store.append_status_change(
        ot_dir,
        ClaimStatusChange(
            problem_id=problem_id,
            claim_id=claim_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            artifact=artifact,
        ),
    )


def _has_verification_artifact(ot_dir: Path, problem_id: str, claim: ClaimRecord) -> bool:
    """A claim is backed by verification if a formal-proof evidence or a verified
    proof attempt is linked to it."""
    evidence_by_id = {e.id: e for e in store.list_evidence(ot_dir, problem_id)}
    for ev_id in claim.evidence_links:
        ev = evidence_by_id.get(ev_id)
        if ev is not None and ev.direction == "supports" and evidence_can_verify(ev.type):
            return True
    for proof in store.list_proof_attempts(ot_dir, problem_id):
        if proof.status == "verified" and claim.id in proof.claim_links:
            return True
    return False


def add_claim(
    ot_dir: Path,
    problem_id: str,
    *,
    claim_type: ClaimType,
    statement: str,
    source_artifacts: list[str] | None = None,
    depends_on: list[str] | None = None,
    confidence: float | None = None,
    notes: str = "",
) -> ClaimRecord:
    store.require_dossier(ot_dir, problem_id)
    sources = source_artifacts or []
    # On creation a verification artifact can only come from an explicitly cited
    # verified proof attempt; evidence is linked later.
    verified_proofs = {
        p.id for p in store.list_proof_attempts(ot_dir, problem_id) if p.status == "verified"
    }
    has_verification = any(s in verified_proofs for s in sources)
    assert_can_create_claim(
        claim_type,
        has_verification_artifact=has_verification,
        has_source_artifact=bool(sources),
    )
    claim = ClaimRecord(
        id=store.next_claim_id(ot_dir, problem_id),
        problem_id=problem_id,
        type=claim_type,
        statement=statement.strip(),
        status=default_status_for_type(claim_type),
        source_artifacts=sources,
        depends_on=depends_on or [],
        confidence=confidence,
        notes=notes,
    )
    return store.append_claim(ot_dir, claim)


def add_evidence(
    ot_dir: Path,
    problem_id: str,
    claim_id: str,
    *,
    evidence_type: EvidenceType,
    summary: str = "",
    direction: EvidenceDirection = "supports",
    path: str | None = None,
    source_artifacts: list[str] | None = None,
    limitations: list[str] | None = None,
) -> tuple[EvidenceRecord, str | None]:
    """Link evidence to a claim. Returns (evidence, advisory).

    Supporting evidence may softly move ``unverified`` → ``supported``;
    contradicting evidence moves the claim to ``contradicted`` and returns an
    advisory. Evidence never reaches a verified status — that needs verification.
    """
    claim = store.get_claim(ot_dir, problem_id, claim_id)
    if claim is None:
        raise OpenTorusError(f"No claim '{claim_id}' in dossier '{problem_id}'.")

    # An EXPERIMENT citation must reference a real EXP-* manifest. A hallucinated id
    # is rejected outright; a real but not-yet-run experiment is recorded but flagged
    # (its results do not exist yet, so citing them as settled would be dishonest).
    exp_advisory: str | None = None
    if evidence_type == "EXPERIMENT":
        from opentorus.research.dossier.experiments import get_experiment

        for art in source_artifacts or []:
            if not _EXP_ID_RE.match(art.strip()):
                continue
            exp = get_experiment(ot_dir, problem_id, art.strip())
            if exp is None:
                raise OpenTorusError(
                    f"Cannot cite experiment '{art}': no such EXP-* manifest in dossier "
                    f"'{problem_id}'. Create and run it (exp_new → exp_run) before citing it."
                )
            if exp.status == "planned":
                exp_advisory = (
                    f"{art} is planned (not run); its results do not exist yet. Run it "
                    "before relying on its outcome — this is support, never proof."
                )

    evidence = EvidenceRecord(
        id=store.next_evidence_id(ot_dir, problem_id),
        problem_id=problem_id,
        claim_id=claim_id,
        type=evidence_type,
        summary=summary,
        direction=direction,
        path=path,
        source_artifacts=source_artifacts or [],
        limitations=limitations or [],
    )
    store.append_evidence(ot_dir, evidence)

    # exp_advisory is the lowest-priority note; a path or contradiction note overrides it.
    advisory: str | None = exp_advisory
    if path is not None and not (ot_dir.parent / path).exists() and not Path(path).exists():
        advisory = f"Evidence path '{path}' does not exist on disk yet."

    # Update the claim's links and (honestly) its status.
    claims = store.list_claims(ot_dir, problem_id)
    transition: tuple[str, str] | None = None
    for c in claims:
        if c.id != claim_id:
            continue
        if evidence.id not in c.evidence_links:
            c.evidence_links.append(evidence.id)
        old_status = c.status
        if direction == "supports" and c.status == "unverified":
            c.status = "supported"
        elif direction == "contradicts" and c.status in ("unverified", "supported"):
            c.status = "contradicted"
            advisory = (
                f"{evidence.id} contradicts {claim_id}; status set to 'contradicted'. "
                "Review the claim — contradictory evidence is preserved, not discarded."
            )
        if c.status != old_status:
            transition = (old_status, c.status)
        c.updated_at = utcnow()
    store.rewrite_claims(ot_dir, problem_id, claims)
    if transition is not None:
        _log_status_change(
            ot_dir,
            problem_id,
            claim_id,
            transition[0],
            transition[1],
            reason=f"evidence {evidence.id} ({direction})",
            artifact=evidence.id,
        )
    return evidence, advisory


def set_claim_status(
    ot_dir: Path, problem_id: str, claim_id: str, new_status: ClaimStatus
) -> ClaimRecord:
    """Set a claim's status, enforcing that verified statuses need a verification artifact."""
    claim = store.get_claim(ot_dir, problem_id, claim_id)
    if claim is None:
        raise OpenTorusError(f"No claim '{claim_id}' in dossier '{problem_id}'.")
    assert_can_set_status(
        new_status,
        has_verification_artifact=_has_verification_artifact(ot_dir, problem_id, claim),
    )
    old_status = claim.status
    claims = store.list_claims(ot_dir, problem_id)
    for c in claims:
        if c.id == claim_id:
            c.status = new_status
            c.updated_at = utcnow()
    store.rewrite_claims(ot_dir, problem_id, claims)
    _log_status_change(
        ot_dir, problem_id, claim_id, old_status, new_status, reason="manual status update"
    )
    updated = store.get_claim(ot_dir, problem_id, claim_id)
    assert updated is not None
    return updated


def downgrade_claim_type(
    ot_dir: Path,
    problem_id: str,
    claim_id: str,
    new_type: ClaimType,
    *,
    reason: str = "",
) -> ClaimRecord:
    """Downgrade a claim's *type* (e.g. THEOREM → CONJECTURE) and flag it for review.

    Used by the referee to act on a recommended downgrade. This only ever *weakens*
    a claim (an over-stated theorem becomes a conjecture); it never upgrades truth
    status. The change is logged in the status changelog, never silent. Promotions
    to a verified type are refused — those require the verification CRUD.
    """
    if new_type in ("THEOREM", "COUNTEREXAMPLE_VERIFIED", "FORMAL_PROOF_VERIFIED"):
        raise OpenTorusError(
            f"downgrade_claim_type only weakens a claim; '{new_type}' is not a downgrade. "
            "Use the verification CRUD to assert a settled result."
        )
    claim = store.get_claim(ot_dir, problem_id, claim_id)
    if claim is None:
        raise OpenTorusError(f"No claim '{claim_id}' in dossier '{problem_id}'.")
    old_type = claim.type
    old_status = claim.status
    claims = store.list_claims(ot_dir, problem_id)
    for c in claims:
        if c.id == claim_id:
            c.type = new_type
            # A downgraded claim is, by construction, not settled; mark it for review
            # unless it is already in a terminal/non-verified state.
            if c.status in ("verified", "formally_verified", "supported", "unverified"):
                c.status = "needs_review"
            c.updated_at = utcnow()
    store.rewrite_claims(ot_dir, problem_id, claims)
    updated = store.get_claim(ot_dir, problem_id, claim_id)
    assert updated is not None
    _log_status_change(
        ot_dir,
        problem_id,
        claim_id,
        old_status,
        updated.status,
        reason=reason or f"type downgraded {old_type} → {new_type}",
    )
    return updated


def add_proof_attempt(
    ot_dir: Path,
    problem_id: str,
    *,
    title: str,
    body: str,
    kind: str = "sketch",
    scope: str = "primary",
    gaps: list[str] | None = None,
    claim_links: list[str] | None = None,
) -> ProofAttempt:
    """Record a proof sketch or formal attempt. A sketch is never a verified proof."""
    store.require_dossier(ot_dir, problem_id)
    if kind not in ("sketch", "formal"):
        raise OpenTorusError("Proof attempt kind must be 'sketch' or 'formal'.")
    if scope not in ("primary", "exploration"):
        raise OpenTorusError("Proof scope must be 'primary' or 'exploration'.")
    proof_id = store.next_proof_id(ot_dir, problem_id)
    rel_body = f"proof_attempts/{proof_id}.md"
    scope_note = ""
    if scope == "exploration":
        scope_note = " · **exploration** (NOT the dossier answer — speculative connection)"
    (store.dossier_dir(ot_dir, problem_id) / rel_body).write_text(
        f"# {proof_id} — {title}\n\n_Status: {kind} (NOT machine-checked){scope_note}_\n\n{body}\n",
        encoding="utf-8",
    )
    proof = ProofAttempt(
        id=proof_id,
        problem_id=problem_id,
        title=title,
        kind="formal" if kind == "formal" else "sketch",
        scope="exploration" if scope == "exploration" else "primary",
        status="sketch" if kind == "sketch" else "in_progress",
        body_path=rel_body,
        gaps=gaps or [],
        claim_links=claim_links or [],
    )
    return store.append_proof_attempt(ot_dir, proof)


def verify_counterexample(
    ot_dir: Path,
    problem_id: str,
    claim_id: str,
    *,
    verification_artifact: str,
    summary: str = "",
) -> ClaimRecord:
    """Promote a COUNTEREXAMPLE_CANDIDATE to COUNTEREXAMPLE_VERIFIED.

    Requires an explicit verification artifact (a verified proof attempt id or a
    FORMAL_PROOF evidence id). Without it, the candidate stays a candidate.
    """
    claim = store.get_claim(ot_dir, problem_id, claim_id)
    if claim is None:
        raise OpenTorusError(f"No claim '{claim_id}' in dossier '{problem_id}'.")
    if claim.type != "COUNTEREXAMPLE_CANDIDATE":
        raise OpenTorusError(
            f"{claim_id} is '{claim.type}', not a COUNTEREXAMPLE_CANDIDATE; nothing to verify."
        )
    verified_proofs = {
        p.id for p in store.list_proof_attempts(ot_dir, problem_id) if p.status == "verified"
    }
    # Only *supporting* verification-grade evidence may verify the counterexample;
    # a formal proof that contradicts (or is neutral to) the candidate must not
    # promote it. This mirrors ``_has_verification_artifact``.
    formal_evidence = {
        e.id
        for e in store.list_evidence(ot_dir, problem_id)
        if evidence_can_verify(e.type) and e.direction == "supports"
    }
    if verification_artifact not in verified_proofs | formal_evidence:
        raise OpenTorusError(
            f"'{verification_artifact}' is not a verification artifact (a verified "
            "proof attempt or FORMAL_PROOF evidence). Cannot mark the counterexample "
            "as verified."
        )
    old_status = claim.status
    claims = store.list_claims(ot_dir, problem_id)
    for c in claims:
        if c.id == claim_id:
            c.type = "COUNTEREXAMPLE_VERIFIED"
            c.status = "verified"
            if verification_artifact not in c.source_artifacts:
                c.source_artifacts.append(verification_artifact)
            if summary:
                c.notes = (c.notes + "\n" + summary).strip()
            c.updated_at = utcnow()
    store.rewrite_claims(ot_dir, problem_id, claims)
    _log_status_change(
        ot_dir,
        problem_id,
        claim_id,
        old_status,
        "verified",
        reason="counterexample verified",
        artifact=verification_artifact,
    )
    updated = store.get_claim(ot_dir, problem_id, claim_id)
    assert updated is not None
    return updated
