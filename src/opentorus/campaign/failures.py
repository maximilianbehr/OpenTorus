"""Failed-attempt memory: failure signatures and the retry verdict.

A campaign must not spend budget re-running the same doomed attempt. Every worker
failure is summarised as a :class:`FailureSignature`; its ``key`` is a sha256 over the
*normalised* facts that decide whether a retry is the same attempt — strategy class,
target obligation, assumption context, tool/solver, error category, counterargument —
and deliberately **not** over the artifact ids or the occurrence count: two runs that
fail the same way on different scaffolding are the same failure. Before the engine
schedules a work item that would repeat a recorded signature it asks
:func:`retry_verdict`; unless something material changed (:class:`RetryChanges`) the
retry is refused (``retry_refused`` event) and the branch is suspended with the
reactivation conditions of :func:`reactivation_conditions_for`. When a retry is
allowed, ``why_different`` is appended to the signature's ``retry_notes`` so the log
says why the engine thought it worth trying again.

Nothing here reads a clock or the disk: ids are minted by the engine from the
snapshot's ``FSIG`` counter, and every input is a snapshot or a value the engine
derived from the dossier.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from opentorus.agent.control.models import ReasonCode
from opentorus.campaign.models import (
    CampaignSnapshot,
    ErrorCategory,
    FailureSignature,
    ReactivationCondition,
    WorkerRole,
)

# Error categories whose reactivation hinges on the verification stack changing.
BACKEND_CATEGORIES: frozenset[str] = frozenset(
    {"tool_unavailable", "verifier_rejected", "verifier_inconclusive"}
)
# Categories whose reactivation hinges on new evidence about the problem.
EVIDENCE_CATEGORIES: frozenset[str] = frozenset({"no_witness_found", "model_no_progress"})


def normalize_text(text: str) -> str:
    """Case- and whitespace-insensitive form of a free-text field."""
    return " ".join(text.lower().split())


def normalize_context(context: Iterable[str]) -> list[str]:
    """Sorted, normalised, de-duplicated assumption context (order must not matter)."""
    return sorted({normalize_text(c) for c in context if c and c.strip()})


def signature_key(sig: FailureSignature) -> str:
    """The sha256 that identifies *what failed*, independent of ids and counts."""
    payload = [
        normalize_text(sig.strategy_class),
        normalize_text(sig.target_obligation or ""),
        normalize_context(sig.assumption_context),
        normalize_text(sig.tool_or_solver),
        str(sig.error_category),
        normalize_text(sig.counterargument),
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def build_failure_signature(
    *,
    role: WorkerRole,
    strategy_class: str,
    target_obligation: str | None = None,
    assumption_context: Sequence[str] = (),
    tool_or_solver: str = "",
    error_category: ErrorCategory = "other",
    counterargument: str = "",
    artifact_ids: Sequence[str] = (),
    branch_id: str | None = None,
    work_item_id: str | None = None,
    verifier_backends: Sequence[str] = (),
) -> FailureSignature:
    """A signature with its key computed; ``signature_id`` is left empty for the engine
    to mint (or to reuse from an existing signature with the same key)."""
    sig = FailureSignature(
        signature_id="",
        key="",
        strategy_class=strategy_class or role.value,
        target_obligation=target_obligation,
        assumption_context=normalize_context(assumption_context),
        tool_or_solver=tool_or_solver,
        error_category=error_category,
        counterargument=counterargument.strip(),
        artifact_ids=list(artifact_ids),
        branch_id=branch_id,
        work_item_id=work_item_id,
        verifier_backends=sorted(verifier_backends),
    )
    sig.key = signature_key(sig)
    return sig


def find_signature(snapshot: CampaignSnapshot, key: str) -> FailureSignature | None:
    """The recorded signature with ``key`` (lowest id when several exist), or ``None``."""
    matches = sorted(
        (s for s in snapshot.failure_signatures.values() if s.key == key),
        key=lambda s: s.signature_id,
    )
    return matches[0] if matches else None


@dataclass(frozen=True)
class RetryChanges:
    """What differs now from when the signature was recorded — the *only* grounds
    for retrying an identical attempt. Every flag is computed by the engine from
    facts (never guessed); ``human_override`` is reserved for an explicit
    ``campaign resume`` after a human changed the problem and is never set by code."""

    assumptions_changed: bool = False
    obligation_changed: bool = False
    new_theorem_refs: int = 0
    new_evidence_count: int = 0
    solver_changed: bool = False
    parameter_regime_changed: bool = False
    verification_backend_changed: bool = False
    human_override: bool = False
    # A provider/transport failure is an infrastructure fact, not a verdict on the
    # strategy: once the campaign has been resumed *after* the failure was recorded,
    # the endpoint may be back and one identical attempt is a fair test of that.
    provider_recovered: bool = False
    details: tuple[str, ...] = field(default=())

    def any(self) -> bool:
        return bool(
            self.assumptions_changed
            or self.obligation_changed
            or self.new_theorem_refs > 0
            or self.new_evidence_count > 0
            or self.solver_changed
            or self.parameter_regime_changed
            or self.verification_backend_changed
            or self.human_override
            or self.provider_recovered
        )

    def describe(self) -> str:
        parts: list[str] = []
        if self.assumptions_changed:
            parts.append("assumption context changed")
        if self.obligation_changed:
            parts.append("target obligation changed")
        if self.new_theorem_refs > 0:
            parts.append(f"{self.new_theorem_refs} new theorem reference(s)")
        if self.new_evidence_count > 0:
            parts.append(f"{self.new_evidence_count} new evidence record(s)")
        if self.solver_changed:
            parts.append("solver/tool changed")
        if self.parameter_regime_changed:
            parts.append("parameter regime changed")
        if self.verification_backend_changed:
            parts.append("verification backend changed")
        if self.human_override:
            parts.append("human override")
        if self.provider_recovered:
            parts.append("campaign resumed after a provider outage (endpoint may be back)")
        text = "; ".join(parts)
        if self.details:
            text = f"{text} ({'; '.join(self.details)})" if text else "; ".join(self.details)
        return text


class RetryVerdict(BaseModel):
    allowed: bool
    reason_code: str
    why_different: str = ""
    signature_id: str | None = None


def retry_verdict(key: str, snapshot: CampaignSnapshot, changes: RetryChanges) -> RetryVerdict:
    """May an attempt with signature ``key`` run again?

    * no recorded signature with that key → allowed (nothing to repeat);
    * recorded and something in ``changes`` differs → allowed, ``why_different`` set;
    * recorded and nothing changed → refused with ``REPEATED_IDENTICAL_FAILURE``.
    """
    prior = find_signature(snapshot, key)
    if prior is None:
        return RetryVerdict(allowed=True, reason_code=ReasonCode.OK.value, why_different="")
    if changes.any():
        return RetryVerdict(
            allowed=True,
            reason_code=ReasonCode.OK.value,
            why_different=changes.describe(),
            signature_id=prior.signature_id,
        )
    return RetryVerdict(
        allowed=False,
        reason_code=ReasonCode.REPEATED_IDENTICAL_FAILURE.value,
        why_different=(
            f"{prior.signature_id} ({prior.error_category}) recorded {prior.occurrences}x with "
            "the same strategy, obligation, assumptions, tool and counterargument; nothing "
            "changed since"
        ),
        signature_id=prior.signature_id,
    )


def reactivation_conditions_for(
    sig: FailureSignature,
    *,
    evidence_count: int,
    verifier_backends: Sequence[str],
    accepted_theorem_refs: int,
    last_resume_seq: int = 0,
) -> list[ReactivationCondition]:
    """The conditions under which a branch suspended for ``sig`` may run again.

    They name what the scheduler must *observe later*: a changed verifier stack for
    tool/verifier failures, more evidence about the problem for a witness/no-progress
    failure, an accepted theorem reference for an invalid citation. Every condition
    records what was observed at suspension so "changed" is checkable, not vibes.
    """
    conditions: list[ReactivationCondition] = []
    category = str(sig.error_category)
    if category in BACKEND_CATEGORIES:
        conditions.append(
            ReactivationCondition(
                kind="verification_backend_changed",
                reference=",".join(sorted(verifier_backends)),
                observed_at_suspension=float(len(verifier_backends)),
            )
        )
    if category in EVIDENCE_CATEGORIES:
        conditions.append(
            ReactivationCondition(
                kind="new_evidence_count",
                reference=sig.branch_id,
                threshold=float(evidence_count + 1),
                observed_at_suspension=float(evidence_count),
            )
        )
    if category == "citation_invalid":
        conditions.append(
            ReactivationCondition(
                kind="theorem_ref_accepted",
                reference=sig.branch_id,
                threshold=float(accepted_theorem_refs + 1),
                observed_at_suspension=float(accepted_theorem_refs),
            )
        )
    if category == "provider_unavailable":
        # The endpoint, not the strategy, failed: the next ``campaign resume`` (a human
        # saying "the provider is back") is the trigger — recorded as the resume seq
        # observed now, so "resumed since" is checkable.
        conditions.append(
            ReactivationCondition(
                kind="campaign_resumed",
                reference=sig.branch_id,
                observed_at_suspension=float(last_resume_seq),
            )
        )
    if not conditions:
        # Other categories (permission, budget, timeout, other) have no automatic
        # trigger: only a human decision reactivates the branch.
        conditions.append(ReactivationCondition(kind="human_override", reference=sig.branch_id))
    return conditions


__all__ = [
    "BACKEND_CATEGORIES",
    "EVIDENCE_CATEGORIES",
    "RetryChanges",
    "RetryVerdict",
    "build_failure_signature",
    "find_signature",
    "normalize_context",
    "normalize_text",
    "reactivation_conditions_for",
    "retry_verdict",
    "signature_key",
]
