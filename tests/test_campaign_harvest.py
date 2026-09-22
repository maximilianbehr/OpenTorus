"""Worker-ledger harvest: workspace evidence and failure signatures reach the dossier.

Pins the fix for a live campaign (fisk-toeplitz-minors, 2026-08-19) where the
falsifier's contradicting workspace evidence and the campaign's failure
signatures were invisible to the dossier report, referee and verdict — the
counterexample thread died with the worker session (epistemic invariant 5).
"""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.failures import build_failure_signature
from opentorus.campaign.harvest import harvest_worker_ledgers
from opentorus.campaign.models import WorkerRole
from opentorus.research.claims import new_claim
from opentorus.research.dossier import store as dstore
from opentorus.research.dossier.claims import add_claim
from opentorus.research.evidence import add_evidence
from support.campaign import make_workspace


def _primary(ot: Path, pid: str) -> str:
    primary = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for all n.")
    dossier = dstore.require_dossier(ot, pid)
    dossier.primary_claim_id = primary.id
    dstore.save_dossier(ot, dossier)
    return primary.id


def _signature(counterargument: str = "search output could not be parsed"):
    sig = build_failure_signature(
        role=WorkerRole.falsifier,
        strategy_class="counterexample_search",
        tool_or_solver="counterexample_search",
        error_category="witness_unconfirmed",
        counterargument=counterargument,
        artifact_ids=["EXP-0004"],
    )
    return sig.model_copy(update={"signature_id": "FSIG-0001"})


def test_worker_evidence_is_mirrored_onto_the_primary_claim(tmp_path: Path) -> None:
    _root, ot, pid = make_workspace(tmp_path)
    primary_id = _primary(ot, pid)
    worker_claim = new_claim(ot, "The conjecture is false for the 4-vertex block graph.")
    ws_ev, _ = add_evidence(
        ot,
        worker_claim.id,
        source_type="manual_note",
        summary="T_3[p](z) is not real-rooted for the candidate p",
        direction="contradicts",
        strength="strong",
    )
    notes = harvest_worker_ledgers(ot, pid, "CAMPAIGN-0001", [_signature()])
    mirrored = dstore.list_evidence(ot, pid)
    assert len(mirrored) == 1
    rec = mirrored[0]
    assert rec.claim_id == primary_id
    assert ws_ev.id in rec.source_artifacts and "CAMPAIGN-0001" in rec.source_artifacts
    # the re-aim is named, together with the direction the worker judged *its* claim by
    assert f"[worker claim {worker_claim.id}; contradicts that claim]" in rec.summary
    assert any("workspace strength: strong" in lim for lim in rec.limitations)
    assert any("unreviewed" in lim for lim in rec.limitations)
    # The direction was relative to the worker's own claim, not to the primary target,
    # so it does not travel: the record is neutral on the primary claim, the candidate
    # is visible to report/referee/verdict, and the primary claim's status is untouched.
    assert rec.direction == "neutral"
    assert any("mirrored as neutral" in lim for lim in rec.limitations)
    claim = dstore.get_claim(ot, pid, primary_id)
    assert claim is not None and claim.status == "unverified"
    assert rec.id in claim.evidence_links
    # failure signatures land as first-class failed attempts
    failed = dstore.list_failed_attempts(ot, pid)
    assert len(failed) == 1
    assert "FSIG-0001" in failed[0].artifacts and "EXP-0004" in failed[0].artifacts
    assert failed[0].reason_failed == "witness_unconfirmed"
    assert any("mirrored" in n for n in notes)


def test_refuted_branch_lemma_does_not_contradict_the_primary_claim(tmp_path: Path) -> None:
    """Pins the 2026-09-22 MF-13 / IV-01 harvest: a prover refuted its own auxiliary shift
    lemma (strong, EXPERIMENT-backed) and a formalizer recorded an unvalidated z3 model
    against a branch claim; both were mirrored as *contradicting the conjecture*, which
    marked the primary claim 'contradicted' in the dossier, report and verdict."""
    _root, ot, pid = make_workspace(tmp_path)
    primary_id = _primary(ot, pid)
    lemma = new_claim(ot, "SHIFT LEMMA: g(A) is invariant under A -> A + cI.")
    ws_ev, _ = add_evidence(
        ot,
        lemma.id,
        source_type="experiment",
        summary="REFUTED. The naive shift claim is false: the skew part does not vanish.",
        direction="contradicts",
        strength="strong",
    )
    candidate = new_claim(ot, "Branch claim: the corner inequality holds for this orbit.")
    add_evidence(
        ot,
        candidate.id,
        source_type="log",
        summary="smt returned a candidate model (UNVALIDATED)",
        direction="contradicts",
        strength="weak",
    )
    harvest_worker_ledgers(ot, pid, "CAMPAIGN-0001", [])
    mirrored = dstore.list_evidence(ot, pid)
    assert [e.claim_id for e in mirrored] == [primary_id, primary_id]
    assert {e.direction for e in mirrored} == {"neutral"}
    first = next(e for e in mirrored if ws_ev.id in e.source_artifacts)
    assert first.summary.startswith(f"[worker claim {lemma.id}; contradicts that claim] REFUTED.")
    assert any(f"relative to worker claim {lemma.id}" in lim for lim in first.limitations)
    claim = dstore.get_claim(ot, pid, primary_id)
    assert claim is not None and claim.status == "unverified"
    assert dstore.list_status_changes(ot, pid) == []


def test_evidence_recorded_on_the_primary_claim_id_keeps_its_direction(tmp_path: Path) -> None:
    """A worker with evidence about the *target* records it on the dossier claim id; that
    direction is kept and the dossier's soft 'contradicted' move still applies."""
    _root, ot, pid = make_workspace(tmp_path)
    primary_id = _primary(ot, pid)
    ws_ev, _ = add_evidence(
        ot,
        primary_id,
        source_type="manual_note",
        summary="T_3[p](z) is not real-rooted for the candidate p",
        direction="contradicts",
        strength="strong",
    )
    harvest_worker_ledgers(ot, pid, "CAMPAIGN-0001", [])
    (rec,) = dstore.list_evidence(ot, pid)
    assert rec.claim_id == primary_id and rec.direction == "contradicts"
    assert ws_ev.id in rec.source_artifacts and "[worker claim" not in rec.summary
    claim = dstore.get_claim(ot, pid, primary_id)
    assert claim is not None and claim.status == "contradicted"


def test_harvest_is_idempotent_and_skips_without_a_target_claim(tmp_path: Path) -> None:
    _root, ot, pid = make_workspace(tmp_path)
    worker_claim = new_claim(ot, "Branch-level claim.")
    add_evidence(ot, worker_claim.id, source_type="manual_note", summary="observation")
    # no dossier claim at all: nothing to attach to, and that is said, not invented
    notes = harvest_worker_ledgers(ot, pid, "CAMPAIGN-0001", [])
    assert dstore.list_evidence(ot, pid) == []
    assert any("no dossier claim" in n for n in notes)
    # with a primary claim the same record mirrors exactly once across repeated runs
    _primary(ot, pid)
    harvest_worker_ledgers(ot, pid, "CAMPAIGN-0001", [_signature()])
    harvest_worker_ledgers(ot, pid, "CAMPAIGN-0001", [_signature()])
    assert len(dstore.list_evidence(ot, pid)) == 1
    assert len(dstore.list_failed_attempts(ot, pid)) == 1


def test_a_paused_campaign_still_harvests_its_worker_ledgers(tmp_path: Path) -> None:
    """Round 5: the harvest lived only in SYNTHESIZE, which a bounded run never reaches
    when it pauses on a spent budget — four of eight live campaigns paused and left
    fifteen pieces of worker evidence invisible to their dossiers. Every stop harvests."""
    from opentorus.campaign.models import CampaignStatus
    from opentorus.campaign.store import open_campaign
    from support.campaign import make_engine, make_workspace

    def _status(ot_dir, cid):
        return open_campaign(ot_dir, cid).snapshot.status

    root, ot, pid = make_workspace(tmp_path)
    primary_id = _primary(ot, pid)
    worker_claim = new_claim(ot, "Branch-level claim from a worker.")
    ws_ev, _ = add_evidence(
        ot,
        worker_claim.id,
        source_type="manual_note",
        summary="a bounded search over n <= 40 found no witness",
        direction="supports",
    )
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="exploration", max_steps=1)  # pauses: budget spent
    assert _status(ot, record.id) is CampaignStatus.paused
    mirrored = dstore.list_evidence(ot, pid)
    assert [e.claim_id for e in mirrored] == [primary_id]
    assert ws_ev.id in mirrored[0].source_artifacts
    assert any("unreviewed" in lim for lim in mirrored[0].limitations)
