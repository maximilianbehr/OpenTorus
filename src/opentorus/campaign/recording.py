"""Turning phase results into events: the portfolio and the proof-tree mirror.

Two chunks of bookkeeping the engine's phases delegate here so the phase handlers
stay short: :func:`record_portfolio` writes the ``branch_proposed`` /
``branch_rejected`` / ``branch_activated`` events of a :class:`PortfolioProposal`
(one dossier ``Approach`` per accepted template branch, ids already minted by the
portfolio module from the snapshot counter), and :func:`mirror_graph` mirrors every
artifact reference and obligation as a campaign proof-tree node
(``proof_node_created`` / ``proof_node_updated``). Neither touches a claim status.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from opentorus.agent.control.models import ReasonCode
from opentorus.campaign import events as ev
from opentorus.campaign import ids
from opentorus.campaign.lifecycle import RunContext
from opentorus.campaign.models import (
    ArtifactRef,
    BranchStatus,
    CampaignNodeState,
    ClosureProposal,
    ObligationStatus,
    RootRelation,
    WorkerRole,
)
from opentorus.campaign.portfolio import PortfolioProposal


def record_portfolio(run: RunContext, proposal: PortfolioProposal, ot_dir: Path) -> None:
    """Every proposal becomes ``branch_proposed`` (rejected ones too — they are kept),
    accepted template branches get an ``APPR-*`` approach card, rejections carry their
    reason (``REPEATED_STRATEGY`` / ``PORTFOLIO_CAP`` / ``ROOT_RELATION_REQUIRED``), and
    the chosen initial set is activated slot by slot."""
    from opentorus.research.dossier.strategies import STRATEGY_TEMPLATES, create_approach

    rejected = {b.branch_id: b for b in proposal.rejected}
    accepted_ids = {b.branch_id for b in proposal.accepted}
    for branch in proposal.proposals:
        proposed = branch.model_copy(
            update={"status": BranchStatus.proposed, "rejection_reason": None}
        )
        if proposed.branch_id in accepted_ids and proposed.strategy_key in STRATEGY_TEMPLATES:
            approach = create_approach(ot_dir, run.pid, proposed.strategy_key)
            proposed.approach_id = approach.id
        run.store.append(ev.EventType.branch_proposed, proposed, branch_id=proposed.branch_id)
        if proposed.approach_id:
            run.store.append(
                ev.EventType.artifact_created,
                ArtifactRef(
                    artifact_id=proposed.approach_id, kind="approach", branch_id=proposed.branch_id
                ),
                branch_id=proposed.branch_id,
                refs=[proposed.approach_id],
            )
        reject = rejected.get(proposed.branch_id)
        if reject is not None:
            run.store.append(
                ev.EventType.branch_rejected,
                ev.BranchRejectedPayload(
                    branch_id=proposed.branch_id,
                    reason_code=reject.rejection_reason or ReasonCode.PORTFOLIO_CAP.value,
                    duplicate_of=reject.duplicate_of,
                    note=reject.distinctness_note,
                ),
                branch_id=proposed.branch_id,
            )
        elif run.cfg.require_root_relation and proposed.root_relation is RootRelation.unknown:
            run.store.append(
                ev.EventType.branch_rejected,
                ev.BranchRejectedPayload(
                    branch_id=proposed.branch_id,
                    reason_code="ROOT_RELATION_REQUIRED",
                    note="campaign.require_root_relation is on and the relation is unknown",
                ),
                branch_id=proposed.branch_id,
            )
        run.store.write_branch_card(run.snap.branches[proposed.branch_id])
    slot = 0
    for branch in proposal.activated:
        if run.snap.branches[branch.branch_id].status is not BranchStatus.proposed:
            continue
        slot += 1
        run.store.append(
            ev.EventType.branch_activated,
            ev.BranchActivatedPayload(
                branch_id=branch.branch_id, priority=branch.priority, slot=slot
            ),
            branch_id=branch.branch_id,
        )
        run.store.write_branch_card(run.snap.branches[branch.branch_id])


def mirror_graph(run: RunContext) -> tuple[int, int]:
    """``(created, updated)`` proof-tree nodes for new artifact refs / obligations."""
    snap = run.snap
    by_artifact = {n.artifact_id: n for n in snap.campaign_nodes.values() if n.artifact_id}
    by_obligation = {n.obligation_id: n for n in snap.campaign_nodes.values() if n.obligation_id}
    created = updated = 0
    for ref in snap.artifact_refs:
        if ref.artifact_id in by_artifact:
            continue
        branch = snap.branches.get(ref.branch_id or "")
        node = CampaignNodeState(
            node_id=ids.mint(run.snap.counters, ids.NODE_PREFIX),
            kind=ref.kind,
            title=f"{ref.kind} {ref.artifact_id}",
            artifact_id=ref.artifact_id,
            branch_id=ref.branch_id,
            work_item_id=ref.work_item_id,
            root_relation=branch.root_relation if branch else RootRelation.unknown,
            status="recorded",
        )
        run.store.append(
            ev.EventType.proof_node_created, node, branch_id=ref.branch_id, refs=[ref.artifact_id]
        )
        created += 1
    for oid in sorted(snap.obligations):
        ob = snap.obligations[oid]
        existing = by_obligation.get(oid)
        if existing is None:
            node = CampaignNodeState(
                node_id=ids.mint(run.snap.counters, ids.NODE_PREFIX),
                kind="obligation",
                title=ob.statement[:80],
                statement=ob.statement,
                obligation_id=oid,
                branch_id=ob.branch_id,
                root_relation=ob.root_relation,
                status=ob.status.value,
            )
            run.store.append(
                ev.EventType.proof_node_created, node, branch_id=ob.branch_id, refs=[oid]
            )
            created += 1
        elif existing.status != ob.status.value:
            run.store.append(
                ev.EventType.proof_node_updated,
                ev.ProofNodeUpdatedPayload(
                    node_id=existing.node_id, changes={"status": ob.status.value}
                ),
                branch_id=ob.branch_id,
                refs=[oid],
            )
            updated += 1
    return created, updated


def record_closures(run: RunContext, proposals: Sequence[ClosureProposal]) -> int:
    """``obligation_closed`` for each verifier-coordinator proposal whose obligation is
    still open; returns how many closed. The proposal names the accepted artifact, the
    closure mode and the check that backed it — the only path to a closed obligation."""
    closed = 0
    for proposal in proposals:
        ob = run.snap.obligations.get(proposal.obligation_id)
        if ob is None or ob.status is ObligationStatus.closed:
            continue
        run.store.append(
            ev.EventType.obligation_closed,
            ev.ObligationClosedPayload(
                obligation_id=proposal.obligation_id,
                artifact_id=proposal.artifact_id,
                closure_mode=proposal.mode,
                check_id=proposal.check_id,
                verdict=proposal.verdict,
            ),
            role=WorkerRole.verifier_coordinator,
            branch_id=ob.branch_id,
            refs=[proposal.artifact_id],
        )
        closed += 1
    return closed


__all__ = ["mirror_graph", "record_closures", "record_portfolio"]
