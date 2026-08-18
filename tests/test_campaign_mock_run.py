"""End-to-end mock runs of the campaign engine, asserted structurally.

The digest compares *what happened* — event types, branch statuses and rejection
reasons, failure-signature categories, closures, claim statuses, snapshot == reduce —
never a pinned order or wall-clock seconds, so a legitimate scheduling change does not
break the suite while an epistemic regression does.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from opentorus.campaign import reducer
from opentorus.campaign.clock import StepClock
from opentorus.campaign.models import (
    BranchKind,
    BranchStatus,
    CampaignSnapshot,
    CampaignStatus,
    ObligationStatus,
)
from opentorus.campaign.store import open_campaign
from opentorus.research.dossier import store as dstore
from support.campaign import make_engine, make_workspace


def _digest(snapshot: CampaignSnapshot, types: list[str]) -> dict[str, object]:
    """Structural digest: everything but wall-clock seconds and tokens (excluded by design)."""
    return {
        "event_types": dict(sorted(Counter(types).items())),
        "branches": {
            bid: (b.kind.value, b.status.value, b.rejection_reason, b.suspension_reason)
            for bid, b in sorted(snapshot.branches.items())
        },
        "work_items": {
            wid: (wi.branch_id, wi.role.value, wi.status.value)
            for wid, wi in sorted(snapshot.work_items.items())
        },
        "fsig_categories": sorted(
            (s.signature_id, str(s.error_category), s.occurrences)
            for s in snapshot.failure_signatures.values()
        ),
        "obligations": {
            oid: (o.status.value, o.source_proof_id)
            for oid, o in sorted(snapshot.obligations.items())
        },
        "steps": snapshot.budget.steps_used,
        "rounds": snapshot.rounds,
        "status": snapshot.status.value,
        "completion": snapshot.completion_reason,
        "reactivation": {
            bid: [c.kind for c in b.reactivation_conditions]
            for bid, b in sorted(snapshot.branches.items())
            if b.reactivation_conditions
        },
        "reviews": [(r.kind, r.verdict) for r in snapshot.reviews],
    }


def _run(
    tmp_path: Path, mode: str, **kwargs: object
) -> tuple[Path, str, str, list[str], CampaignSnapshot]:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot, clock=StepClock())
    record = engine.start(pid, mode=mode, **kwargs)  # type: ignore[arg-type]
    store = open_campaign(ot, record.id)
    events, diags = store.read_events()
    assert not diags
    return ot, pid, record.id, [e.type for e in events], store.load().snapshot


def test_prove_or_refute_mock_run_structural_digest(tmp_path: Path) -> None:
    ot, pid, cid, types, snap = _run(tmp_path, "prove-or-refute", branches=4, max_steps=40)
    assert snap.status is CampaignStatus.completed
    # >= 3 distinct branches activated; the mandatory proof + counterexample among them
    activated = {
        e.branch_id for e in open_campaign(ot, cid).read_events()[0] if e.type == "branch_activated"
    }
    assert len(activated) >= 3
    kinds_activated = {snap.branches[b].kind for b in activated if b}
    assert BranchKind.proof in kinds_activated and BranchKind.counterexample in kinds_activated
    assert BranchKind.literature in kinds_activated  # forced: fresh dossier, coverage insufficient
    # 7 template proposals, 4 kept, 3 rejected PORTFOLIO_CAP (preserved)
    assert len(snap.branches) == 7
    assert Counter(b.rejection_reason for b in snap.branches.values())["PORTFOLIO_CAP"] == 3
    # spread scheduling: the first three work items span three distinct branches
    first_three = sorted(snap.work_items.values(), key=lambda wi: wi.work_item_id)[:3]
    assert len({wi.branch_id for wi in first_three}) == 3
    # failure signatures are recorded, honest categories only
    categories = {str(s.error_category) for s in snap.failure_signatures.values()}
    assert categories >= {"no_witness_found", "tool_unavailable"}
    assert "retry_refused" in types and "branch_suspended" in types
    # a proof sketch with obligations exists; zero obligations were closed
    assert types.count("obligation_created") >= 1
    assert "obligation_closed" not in types
    assert all(o.status is ObligationStatus.open for o in snap.obligations.values())
    proofs = dstore.list_proof_attempts(ot, pid)
    assert [p.scope for p in proofs] == ["primary"] and proofs[0].gaps
    # dossier claim statuses unchanged: the primary CONJECTURE stays unverified, no changes
    claims = dstore.list_claims(ot, pid)
    assert [(c.type, c.status) for c in claims] == [("CONJECTURE", "unverified")]
    assert dstore.list_status_changes(ot, pid) == []
    assert dstore.require_dossier(ot, pid).status == "open"
    # every branch ended terminal (completed / suspended / exhausted / rejected)
    assert all(b.status is not BranchStatus.active for b in snap.branches.values())
    # reviews were requested and recorded (critic + referee); nothing machine-checkable
    # was produced under the mock, so no verification was requested or recorded
    assert "review_requested" in types and "review_recorded" in types
    assert "verification_requested" not in types and "verification_recorded" not in types
    # snapshot == reduce(events)
    store = open_campaign(ot, cid)
    events, _ = store.read_events()
    assert reducer.reduce(events).model_dump(mode="json") == json.loads(
        store.snapshot_path.read_text()
    )
    assert store.verify_replay().matches
    assert snap.budget.steps_used <= 40


def test_prove_or_refute_digest_is_identical_across_two_fresh_workspaces(tmp_path: Path) -> None:
    digests = []
    for name in ("a", "b"):
        _ot, _pid, _cid, types, snap = _run(
            tmp_path / name, "prove-or-refute", branches=4, max_steps=40
        )
        digests.append(_digest(snap, types))
    assert digests[0] == digests[1]
    # the event *sequence* is byte-identical too (StepClock; ids from counters)
    logs = []
    for name in ("a", "b"):
        ot = tmp_path / name / ".opentorus"
        events, _ = open_campaign(ot, "CAMPAIGN-0001").read_events()
        logs.append(
            [
                (e.seq, e.type, e.branch_id, e.work_item_id, json.dumps(e.payload, sort_keys=True))
                for e in events
                if e.type != "budget_consumed"  # carries wall seconds
            ]
        )
    assert logs[0] == logs[1]


def test_exploration_and_survey_mock_runs_complete(tmp_path: Path) -> None:
    for mode in ("exploration", "survey"):
        ot, pid, cid, types, snap = _run(tmp_path / mode, mode)
        assert snap.status is CampaignStatus.completed, (mode, snap.completion_reason)
        assert "obligation_closed" not in types
        assert all(b.status is not BranchStatus.active for b in snap.branches.values())
        assert open_campaign(ot, cid).verify_replay().matches
        assert dstore.list_status_changes(ot, pid) == []
        if mode == "survey":
            kinds = Counter(b.kind for b in snap.branches.values())
            assert kinds[BranchKind.literature] >= 3 and kinds[BranchKind.synthesis] == 1
            assert "coverage_assessed" in types
        else:
            assert {b.kind for b in snap.branches.values()} == {
                BranchKind.numerical,
                BranchKind.counterexample,
                BranchKind.literature,
                BranchKind.special_case,
            }
