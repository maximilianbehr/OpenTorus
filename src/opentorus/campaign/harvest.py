"""Mirror worker-session ledgers into the problem dossier at campaign synthesis.

A live campaign's falsifier recorded contradicting workspace evidence (a
counterexample candidate whose stdout ended "CONFIRMED: This is a
counterexample!") that the dossier report, referee and verdict never saw:
worker ledgers live in the workspace stores while the dossier reads only its
own indices, so the campaign closed with the candidate untriaged. Synthesis now
mirrors, as candidate-grade records:

- workspace evidence about the campaign's problem → a dossier ``EvidenceRecord``
  via ``dossier.claims.add_evidence`` (provenance and the worker's strength
  recorded as limitations). Evidence recorded on a dossier claim id keeps its
  direction and the dossier API's own honesty rules apply unchanged: evidence
  never verifies a claim, contradicting evidence soft-moves it to
  ``contradicted`` with a review advisory. Evidence recorded on a *worker-only*
  claim (a branch lemma, a candidate, a proof route) is re-aimed at the primary
  claim so the report, referee and verdict see it — but as ``neutral``: its
  direction was judged against the worker claim, so a refuted lemma must not
  flip the conjecture to ``contradicted`` (two live campaigns, MF-13 and IV-01
  on 2026-09-22, had their primary claim marked contradicted by the refutation
  of an auxiliary shift lemma and by an unvalidated z3 model of a branch claim).
- campaign failure signatures → dossier ``FailedAttempt`` entries, keeping
  failed attempts first-class at the dossier level (epistemic invariant 5).

Mirroring is idempotent: a dossier record that already names the workspace
evidence id (or the signature id) in its artifacts is never mirrored twice, so
pause → resume → synthesize runs are safe.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import cast

from opentorus.campaign.models import FailureSignature

_TYPE_MAP: dict[str, str] = {
    "experiment": "EXPERIMENT",
    "paper": "PAPER",
    "code": "COMPUTATION",
    "log": "MANUAL_NOTE",
    "user_review": "MANUAL_NOTE",
    "external": "REFERENCE",
    "manual_note": "MANUAL_NOTE",
}

_PROVENANCE = "mirrored candidate-grade from a campaign worker session; unreviewed"


def harvest_worker_ledgers(
    ot_dir: Path,
    problem_id: str,
    campaign_id: str,
    failure_signatures: Iterable[FailureSignature] = (),
) -> list[str]:
    """Mirror workspace evidence and failure signatures into the dossier.

    Returns human-readable notes (one per mirrored/skipped record). Never raises
    for a single bad record — synthesis must not be blocked by one entry.
    """
    notes = _mirror_evidence(ot_dir, problem_id, campaign_id)
    notes += _mirror_failures(ot_dir, problem_id, campaign_id, failure_signatures)
    return notes


def _mirror_evidence(ot_dir: Path, problem_id: str, campaign_id: str) -> list[str]:
    from opentorus.research.dossier import claims as dclaims
    from opentorus.research.dossier import store as dstore
    from opentorus.research.dossier.models import EvidenceDirection, EvidenceType
    from opentorus.research.evidence import list_evidence as workspace_evidence

    notes: list[str] = []
    dossier = dstore.require_dossier(ot_dir, problem_id)
    dossier_claims = {c.id for c in dstore.list_claims(ot_dir, problem_id)}
    mirrored = {src for e in dstore.list_evidence(ot_dir, problem_id) for src in e.source_artifacts}
    for ev in workspace_evidence(ot_dir):
        if ev.problem_id not in (None, problem_id):
            continue
        if ev.id in mirrored:
            continue
        direction = cast("EvidenceDirection", ev.direction)
        extra_limitations: list[str] = []
        if ev.claim_id in dossier_claims:
            claim_id, remap = ev.claim_id, ""
        elif dossier.primary_claim_id:
            # A worker's branch-level claim has no dossier twin: attach the evidence to
            # the primary claim, naming the worker claim so nothing is silently re-aimed.
            # The direction was judged against the *worker* claim (a lemma, a candidate,
            # a proof route), not against the primary target, so it cannot travel with
            # the record: a refuted branch lemma is not a refutation of the conjecture,
            # and a confirmed one is not support for it. Re-aimed evidence is mirrored
            # as neutral — preserved in full, but it never moves the primary claim's
            # status. A worker that really has evidence about the target records it on
            # the primary claim id itself, and that direction is kept.
            claim_id = dossier.primary_claim_id
            remap = f"[worker claim {ev.claim_id}; {ev.direction} that claim] "
            if ev.direction != "neutral":
                extra_limitations.append(
                    f"direction '{ev.direction}' was relative to worker claim {ev.claim_id}, "
                    f"which is not a dossier claim; mirrored as neutral on {claim_id} — "
                    "evidence about a branch-level claim never changes the primary claim's status"
                )
            direction = "neutral"
        else:
            notes.append(f"{ev.id} not mirrored: no dossier claim to attach it to")
            continue
        summary = f"{remap}{ev.summary}".strip() or f"{remap}workspace evidence {ev.id}"
        sources = [ev.id, campaign_id, *([ev.source_id] if ev.source_id else [])]
        try:
            record, advisory = dclaims.add_evidence(
                ot_dir,
                problem_id,
                claim_id,
                evidence_type=cast("EvidenceType", _TYPE_MAP.get(ev.source_type, "MANUAL_NOTE")),
                summary=summary,
                direction=direction,
                source_artifacts=sources,
                limitations=[
                    *ev.limitations,
                    *extra_limitations,
                    f"workspace strength: {ev.strength}",
                    _PROVENANCE,
                ],
            )
        except Exception as exc:  # noqa: BLE001 - one bad record must not block the rest
            notes.append(f"{ev.id} not mirrored: {exc}")
            continue
        suffix = f" ({advisory})" if advisory else ""
        notes.append(f"{ev.id} mirrored to {record.id} on {claim_id}{suffix}")
    return notes


def _mirror_failures(
    ot_dir: Path,
    problem_id: str,
    campaign_id: str,
    failure_signatures: Iterable[FailureSignature],
) -> list[str]:
    from opentorus.research.dossier import store as dstore

    notes: list[str] = []
    known = {a for f in dstore.list_failed_attempts(ot_dir, problem_id) for a in f.artifacts}
    for sig in failure_signatures:
        if not sig.signature_id or sig.signature_id in known:
            continue
        try:
            rec = dstore.add_failed_attempt(
                ot_dir,
                problem_id,
                attempted_method=f"{sig.strategy_class} ({sig.tool_or_solver})".strip(),
                summary=sig.counterargument,
                reason_failed=str(sig.error_category),
                artifacts=[sig.signature_id, *sig.artifact_ids],
                tags=["campaign", campaign_id],
            )
        except Exception as exc:  # noqa: BLE001 - one bad record must not block the rest
            notes.append(f"{sig.signature_id} not mirrored: {exc}")
            continue
        notes.append(f"{sig.signature_id} mirrored to {rec.id}")
    return notes


__all__ = ["harvest_worker_ledgers"]
