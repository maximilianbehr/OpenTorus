"""Between rounds: retry gating, suspension, exhaustion, reactivation, queue activation.

The engine's REALLOCATE and SCHEDULE phases call these functions; they live apart
from :mod:`engine` so the phase table stays readable and the rules are testable on
their own. Every decision is an event with its reason:

* :func:`retry_gate` — before a work item is scheduled on a branch whose latest work
  item failed, the branch's failure signature is checked against what changed since
  (:func:`retry_changes`, computed from the snapshot and the derived dossier facts —
  never guessed); an unchanged repeat is ``retry_refused`` and the branch is suspended
  with the reactivation conditions of its category; a changed one is ``retry_allowed``
  and the reason lands in the signature's ``retry_notes``;
* :func:`suspend_and_exhaust` — an active branch with ≥ 2 trailing identical failures
  is suspended (``REPEATED_IDENTICAL_FAILURE``); one out of branch step budget is
  exhausted (``BRANCH_EXHAUSTED``);
* :func:`reactivate` — a suspended branch runs again only when a *recorded*
  reactivation condition is satisfied by the current facts (``branch_reactivated``);
* :func:`activate_queued` — ``proposed`` branches fill free active slots by priority.
"""

from __future__ import annotations

import logging

from opentorus.agent.control.models import ReasonCode
from opentorus.campaign import events as ev
from opentorus.campaign.failures import (
    RetryChanges,
    find_signature,
    normalize_context,
    reactivation_conditions_for,
    retry_verdict,
)
from opentorus.campaign.lifecycle import RunContext
from opentorus.campaign.models import (
    BranchRecord,
    BranchStatus,
    CampaignPhase,
    CampaignSnapshot,
    FailureSignature,
    ObligationStatus,
    WorkItemStatus,
)
from opentorus.campaign.phases import DossierFacts
from opentorus.campaign.scheduler import (
    WorkItemPlan,
    branch_steps_remaining,
    identical_failure_streak,
    reactivation_due,
)
from opentorus.campaign.workers.base import formal_backends
from opentorus.config import Config

_logger = logging.getLogger("opentorus")


def last_entered_seq(snap: CampaignSnapshot, phase: CampaignPhase) -> int:
    """The seq at which ``phase`` was *previously* entered (0 = never before now).

    The current entry (the last one) is skipped: "new since the last CRITIQUE" means
    since the one before this round's.
    """
    entries = [p.entered_seq for p in snap.phase_history if p.phase is phase]
    return entries[-2] if len(entries) >= 2 else 0


# Artifact kinds the critic reviews when they appear in a round.
REVIEWABLE_KINDS: frozenset[str] = frozenset({"claim", "proof_attempt"})


def critique_targets(snap: CampaignSnapshot) -> list[str]:
    """Claims / proof attempts recorded since the previous CRITIQUE — this round's."""
    since = last_entered_seq(snap, CampaignPhase.CRITIQUE)
    return sorted(
        {
            ref.artifact_id
            for ref in snap.artifact_refs
            if ref.kind in REVIEWABLE_KINDS and (ref.seq or 0) > since
        }
    )


def activate_queued(run: RunContext) -> int:
    """Activate ``proposed`` branches while active slots are free (priority, then id)."""
    snap = run.snap
    active = sum(1 for b in snap.branches.values() if b.status is BranchStatus.active)
    queued = sorted(
        (b for b in snap.branches.values() if b.status is BranchStatus.proposed),
        key=lambda b: (-b.priority, b.branch_id),
    )
    slot = active
    count = 0
    for branch in queued:
        if slot >= run.cfg.max_active_branches:
            break
        slot += 1
        count += 1
        run.store.append(
            ev.EventType.branch_activated,
            ev.BranchActivatedPayload(
                branch_id=branch.branch_id, priority=branch.priority, slot=slot
            ),
            branch_id=branch.branch_id,
        )
        run.store.write_branch_card(run.snap.branches[branch.branch_id])
    return count


def retry_changes(
    run: RunContext,
    branch: BranchRecord,
    sig: FailureSignature,
    facts: DossierFacts,
    config: Config,
) -> RetryChanges:
    """What differs now from when ``sig`` was recorded — computed from facts only."""
    snap = run.snap
    since = sig.last_seq or 0
    new_evidence = sum(
        1 for r in snap.artifact_refs if r.kind == "evidence" and (r.seq or 0) > since
    )
    new_refs = sum(
        1 for r in snap.artifact_refs if r.kind == "theorem_reference" and (r.seq or 0) > since
    )
    obligation_changed = False
    if sig.target_obligation:
        ob = snap.obligations.get(sig.target_obligation)
        obligation_changed = ob is not None and ob.status is not ObligationStatus.open
    backends_now = sorted(facts.verifier_backends)
    backend_changed = bool(sig.verifier_backends) and sorted(sig.verifier_backends) != backends_now
    if not sig.verifier_backends and str(sig.error_category) == "tool_unavailable":
        backend_changed = bool(formal_backends(config))
    provider_recovered = str(sig.error_category) == "provider_unavailable" and since < int(
        snap.counters.get("last_resume_seq", 0)
    )
    details: list[str] = []
    if backend_changed:
        details.append(f"backends now: {', '.join(backends_now) or 'none'}")
    return RetryChanges(
        assumptions_changed=(
            normalize_context(branch.assumption_context)
            != normalize_context(sig.assumption_context)
        ),
        obligation_changed=obligation_changed,
        new_theorem_refs=new_refs,
        new_evidence_count=new_evidence,
        solver_changed=False,
        parameter_regime_changed=False,
        verification_backend_changed=backend_changed,
        human_override=False,
        provider_recovered=provider_recovered,
        details=tuple(details),
    )


def suspend(
    run: RunContext,
    branch: BranchRecord,
    sig: FailureSignature | None,
    facts: DossierFacts,
    *,
    why: str,
) -> None:
    """Record ``branch_suspended`` (``REPEATED_IDENTICAL_FAILURE``) with the reactivation
    conditions derived from the signature's category (none without a signature)."""
    conditions = (
        reactivation_conditions_for(
            sig,
            evidence_count=facts.evidence_count,
            verifier_backends=facts.verifier_backends,
            accepted_theorem_refs=facts.accepted_theorem_ref_count,
            last_resume_seq=int(run.snap.counters.get("last_resume_seq", 0)),
        )
        if sig is not None
        else []
    )
    run.store.append(
        ev.EventType.branch_suspended,
        ev.BranchSuspendedPayload(
            branch_id=branch.branch_id,
            reason_code=ReasonCode.REPEATED_IDENTICAL_FAILURE.value,
            reactivation_conditions=conditions,
        ),
        branch_id=branch.branch_id,
        refs=[sig.signature_id] if sig is not None else [],
    )
    run.store.write_branch_card(run.snap.branches[branch.branch_id])
    _logger.info("branch %s suspended: %s", branch.branch_id, why)


def retry_gate(run: RunContext, plan: WorkItemPlan, facts: DossierFacts, config: Config) -> bool:
    """May ``plan``'s branch run again? False → ``retry_refused`` + suspension recorded."""
    snap = run.snap
    branch = snap.branches[plan.branch_id]
    if branch.consecutive_failures < 1 or not branch.failure_signatures:
        return True
    last_id = branch.failure_signatures[-1]
    sig = snap.failure_signatures.get(last_id)
    if sig is None:
        return True
    # Only the signature of the *latest* failed work item gates the retry.
    latest_failed = [
        wi
        for wi in (snap.work_items.get(w) for w in branch.work_item_ids)
        if wi is not None and wi.status is WorkItemStatus.failed
    ]
    if latest_failed and latest_failed[-1].failure_signature_id:
        latest = snap.failure_signatures.get(latest_failed[-1].failure_signature_id)
        if latest is not None:
            sig = latest
    verdict = retry_verdict(sig.key, snap, retry_changes(run, branch, sig, facts, config))
    if verdict.allowed:
        if verdict.why_different:
            run.store.append(
                ev.EventType.retry_allowed,
                ev.RetryAllowedPayload(
                    branch_id=branch.branch_id,
                    signature_id=sig.signature_id,
                    reason_code=verdict.reason_code,
                    why_different=verdict.why_different,
                ),
                branch_id=branch.branch_id,
                refs=[sig.signature_id],
            )
        return True
    run.store.append(
        ev.EventType.retry_refused,
        ev.RetryRefusedPayload(
            branch_id=branch.branch_id,
            signature_id=sig.signature_id,
            reason_code=verdict.reason_code,
            why_refused=verdict.why_different,
        ),
        branch_id=branch.branch_id,
        refs=[sig.signature_id],
    )
    suspend(run, branch, sig, facts, why="retry refused: " + verdict.why_different)
    return False


def suspend_and_exhaust(run: RunContext, facts: DossierFacts) -> str:
    """Suspend active branches with ≥ 2 trailing identical failures; exhaust the ones
    out of branch step budget. Returns a note for the phase outcome."""
    notes: list[str] = []
    for bid in sorted(run.snap.branches):
        branch = run.snap.branches[bid]
        if branch.status is not BranchStatus.active:
            continue
        streak, key = identical_failure_streak(branch, run.snap)
        if streak >= 2 and key is not None:
            suspend(
                run,
                branch,
                find_signature(run.snap, key),
                facts,
                why=f"{streak} identical failures",
            )
            notes.append(f"{bid} suspended ({streak} identical failures)")
            continue
        if branch_steps_remaining(branch, run.snap, run.cfg.branch_step_budget) <= 0:
            run.store.append(
                ev.EventType.branch_exhausted,
                ev.BranchTerminalPayload(
                    branch_id=bid,
                    reason=f"{ReasonCode.BRANCH_EXHAUSTED.value}: branch step budget "
                    f"({run.cfg.branch_step_budget}) spent",
                ),
                branch_id=bid,
            )
            run.store.write_branch_card(run.snap.branches[bid])
            notes.append(f"{bid} exhausted (branch step budget)")
    return "; ".join(notes)


def reactivate(run: RunContext, facts: DossierFacts) -> str:
    """Reactivate suspended branches whose recorded condition the facts now satisfy."""
    notes: list[str] = []
    for bid in sorted(run.snap.branches):
        branch = run.snap.branches[bid]
        if branch.status is not BranchStatus.suspended:
            continue
        cond = reactivation_due(branch, run.snap, facts)
        if cond is None:
            continue
        observed = {
            "verification_backend_changed": ", ".join(facts.verifier_backends) or "none",
            "new_evidence_count": str(facts.evidence_count),
            "theorem_ref_accepted": str(facts.accepted_theorem_ref_count),
        }.get(cond.kind, cond.kind)
        run.store.append(
            ev.EventType.branch_reactivated,
            ev.BranchReactivatedPayload(
                branch_id=bid, condition_met=cond, observed=f"{cond.kind}: {observed}"
            ),
            branch_id=bid,
        )
        run.store.write_branch_card(run.snap.branches[bid])
        notes.append(f"{bid} reactivated ({cond.kind})")
    return "; ".join(notes)


__all__ = [
    "REVIEWABLE_KINDS",
    "activate_queued",
    "critique_targets",
    "last_entered_seq",
    "reactivate",
    "retry_changes",
    "retry_gate",
    "suspend",
    "suspend_and_exhaust",
]
