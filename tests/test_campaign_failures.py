"""Failed-attempt memory: signature keys, retry verdicts, and the engine's refusal to
re-run an unchanged failure (``retry_refused``) versus a changed one (``retry_allowed``)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from opentorus.campaign.failures import (
    RetryChanges,
    build_failure_signature,
    find_signature,
    reactivation_conditions_for,
    retry_verdict,
    signature_key,
)
from opentorus.campaign.models import (
    BranchKind,
    CampaignMode,
    CampaignSnapshot,
    FailureSignature,
    WorkerRole,
)
from opentorus.campaign.store import open_campaign
from support.campaign import make_engine, make_workspace


def _sig(**overrides: object) -> FailureSignature:
    base: dict[str, object] = {
        "role": WorkerRole.prover,
        "strategy_class": "proof_sketch",
        "target_obligation": "OBL-0001",
        "assumption_context": ["n >= 1", "P is monotone"],
        "tool_or_solver": "proof_write",
        "error_category": "model_no_progress",
        "counterargument": "no proof_write in 3 turns",
        "artifact_ids": ["PROOF-0001"],
    }
    base.update(overrides)
    return build_failure_signature(**base)  # type: ignore[arg-type]


def test_signature_key_ignores_artifact_ids_and_occurrences() -> None:
    a = _sig()
    b = _sig(artifact_ids=["PROOF-0002", "EXP-0007"], branch_id="BRANCH-0002", work_item_id="WI-9")
    b.occurrences = 5
    assert a.key == b.key == signature_key(a)
    # normalisation: case, whitespace, order of the assumption context
    c = _sig(
        assumption_context=["P is  monotone", "N >= 1"],
        counterargument="  NO proof_write in 3 turns ",
        strategy_class="Proof_Sketch",
    )
    assert c.key == a.key
    assert c.assumption_context == ["n >= 1", "p is monotone"]  # stored normalised, sorted
    # any material field changes the key
    for change in (
        {"strategy_class": "special_cases"},
        {"target_obligation": "OBL-0002"},
        {"assumption_context": ["n >= 1"]},
        {"tool_or_solver": "lean4"},
        {"error_category": "verifier_rejected"},
        {"counterargument": "sympy rejected"},
    ):
        assert _sig(**change).key != a.key, change
    assert a.signature_id == ""  # minted by the engine


def _snapshot_with(sig: FailureSignature) -> CampaignSnapshot:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    snap = CampaignSnapshot(
        campaign_id="CAMPAIGN-0001",
        problem_id="PROBLEM-0001",
        mode=CampaignMode.prove_or_refute,
        created_at=ts,
        updated_at=ts,
    )
    recorded = sig.model_copy(update={"signature_id": "FSIG-0001", "occurrences": 2})
    snap.failure_signatures = {"FSIG-0001": recorded}
    return snap


def test_retry_verdict_refuses_unchanged_and_permits_changed() -> None:
    sig = _sig()
    snap = _snapshot_with(sig)
    assert find_signature(snap, sig.key) is not None
    refused = retry_verdict(sig.key, snap, RetryChanges())
    assert not refused.allowed
    assert refused.reason_code == "REPEATED_IDENTICAL_FAILURE"
    assert "FSIG-0001" in refused.why_different and "2x" in refused.why_different
    assert refused.signature_id == "FSIG-0001"
    # a never-seen key is always allowed
    fresh = retry_verdict("nope", snap, RetryChanges())
    assert fresh.allowed and fresh.reason_code == "OK" and fresh.why_different == ""
    for changes, needle in (
        (RetryChanges(assumptions_changed=True), "assumption context changed"),
        (RetryChanges(new_evidence_count=2), "2 new evidence record(s)"),
        (RetryChanges(new_theorem_refs=1), "1 new theorem reference(s)"),
        (RetryChanges(obligation_changed=True), "target obligation changed"),
        (RetryChanges(solver_changed=True), "solver/tool changed"),
        (RetryChanges(parameter_regime_changed=True), "parameter regime changed"),
        (RetryChanges(verification_backend_changed=True), "verification backend changed"),
        (RetryChanges(human_override=True), "human override"),
    ):
        verdict = retry_verdict(sig.key, snap, changes)
        assert verdict.allowed and verdict.reason_code == "OK", changes
        assert needle in verdict.why_different
    both = RetryChanges(new_evidence_count=1, verification_backend_changed=True, details=("x",))
    assert "new evidence" in both.describe() and "(x)" in both.describe()


def test_reactivation_conditions_follow_the_error_category() -> None:
    backend = reactivation_conditions_for(
        _sig(error_category="tool_unavailable"),
        evidence_count=3,
        verifier_backends=["interval", "sympy"],
        accepted_theorem_refs=0,
    )
    assert [c.kind for c in backend] == ["verification_backend_changed"]
    assert backend[0].reference == "interval,sympy"
    evidence = reactivation_conditions_for(
        _sig(error_category="no_witness_found"),
        evidence_count=3,
        verifier_backends=[],
        accepted_theorem_refs=0,
    )
    assert [c.kind for c in evidence] == ["new_evidence_count"]
    assert evidence[0].threshold == 4.0 and evidence[0].observed_at_suspension == 3.0
    citation = reactivation_conditions_for(
        _sig(error_category="citation_invalid"),
        evidence_count=0,
        verifier_backends=[],
        accepted_theorem_refs=1,
    )
    assert [c.kind for c in citation] == ["theorem_ref_accepted"]
    assert citation[0].threshold == 2.0
    other = reactivation_conditions_for(
        _sig(error_category="budget"),
        evidence_count=0,
        verifier_backends=[],
        accepted_theorem_refs=0,
    )
    assert [c.kind for c in other] == ["human_override"]


def test_engine_refuses_an_unchanged_retry_and_records_it(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="prove-or-refute", branches=4, max_steps=40)
    store = open_campaign(ot, record.id)
    events, _ = store.read_events()
    snap = store.load().snapshot
    refused = [e for e in events if e.type == "retry_refused"]
    assert refused, "the falsifier's/formalizer's unchanged repeats must be refused"
    for event in refused:
        payload = event.payload
        assert payload["reason_code"] == "REPEATED_IDENTICAL_FAILURE"
        sig = snap.failure_signatures[str(payload["signature_id"])]
        assert sig.branch_id == payload["branch_id"] == event.branch_id
        assert any("refused at seq" in note for note in sig.retry_notes)
        # the refused branch was suspended right after, and never ran the same item again
        later = [e for e in events if e.seq > event.seq and e.branch_id == event.branch_id]
        assert later and later[0].type == "branch_suspended"
        assert not any(e.type == "worker_started" for e in later)
    # every failure signature carries occurrences==1: nothing was re-run unchanged
    assert all(s.occurrences == 1 for s in snap.failure_signatures.values())
    assert "retry_allowed" not in {e.type for e in events}


def test_engine_allows_a_retry_when_new_evidence_arrived(tmp_path: Path) -> None:
    """A branch whose failure was 'no witness found' may run again once evidence about
    the problem arrived after the failure — and the log says why."""
    from opentorus.campaign import events as ev
    from opentorus.campaign.models import ArtifactRef, CampaignPhase, CampaignStatus

    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="prove-or-refute", branches=4, max_steps=40, run=False)
    ce_bid: str | None = None

    def _until(snap) -> bool:  # noqa: ANN001
        nonlocal ce_bid
        for b in snap.branches.values():
            if b.kind is BranchKind.counterexample and b.failure_signatures:
                ce_bid = b.branch_id
                return snap.phase is CampaignPhase.CRITIQUE
        return False

    engine.run(record.id, until=_until)
    assert ce_bid is not None
    store = open_campaign(ot, record.id)
    # New evidence recorded on the branch *after* the signature: an artifact_created ref
    # of kind evidence (as the falsifier would report after a real search).
    store.load()
    store.append(
        ev.EventType.artifact_created,
        ArtifactRef(artifact_id="EVIDENCE-0099", kind="evidence", branch_id=ce_bid),
        branch_id=ce_bid,
        refs=["EVIDENCE-0099"],
    )
    engine.pause(record.id, "inject")
    engine.resume(record.id)
    events, _ = store.read_events()
    allowed = [e for e in events if e.type == "retry_allowed" and e.branch_id == ce_bid]
    assert allowed, [e.type for e in events if e.branch_id == ce_bid]
    assert "1 new evidence record(s)" in str(allowed[0].payload["why_different"])
    snap = store.load().snapshot
    sig = snap.failure_signatures[str(allowed[0].payload["signature_id"])]
    assert any("allowed at seq" in note and "new evidence" in note for note in sig.retry_notes)
    # the branch actually ran again after the allowed retry
    starts = [
        e
        for e in events
        if e.type == "worker_started" and e.branch_id == ce_bid and e.seq > allowed[0].seq
    ]
    assert starts
    assert snap.status is CampaignStatus.completed
