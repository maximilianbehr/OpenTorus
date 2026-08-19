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
    assert rec.direction == "contradicts"
    assert ws_ev.id in rec.source_artifacts and "CAMPAIGN-0001" in rec.source_artifacts
    assert f"[worker claim {worker_claim.id}]" in rec.summary  # the re-aim is named
    assert any("workspace strength: strong" in lim for lim in rec.limitations)
    assert any("unreviewed" in lim for lim in rec.limitations)
    # the dossier API's own honesty rules applied: contradicted is a soft, sub-verified
    # status and the claim is linked, never verified
    claim = dstore.get_claim(ot, pid, primary_id)
    assert claim is not None and claim.status == "contradicted"
    assert rec.id in claim.evidence_links
    # failure signatures land as first-class failed attempts
    failed = dstore.list_failed_attempts(ot, pid)
    assert len(failed) == 1
    assert "FSIG-0001" in failed[0].artifacts and "EXP-0004" in failed[0].artifacts
    assert failed[0].reason_failed == "witness_unconfirmed"
    assert any("mirrored" in n for n in notes)


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
