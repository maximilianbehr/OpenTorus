"""The campaign engine on the offline mock path: lifecycle, budgets, invariants,
determinism. No model calls are made anywhere in these tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentorus.campaign import reducer
from opentorus.campaign.clock import StepClock
from opentorus.campaign.engine import (
    PRIMARY_CLAIM_REMEDIATION,
    CampaignConfigError,
    CampaignEngine,
    PhaseOutcome,
)
from opentorus.campaign.models import (
    BranchKind,
    BranchStatus,
    CampaignPhase,
    CampaignSnapshot,
    CampaignStatus,
    RootRelation,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.paths import campaign_dir
from opentorus.campaign.store import CampaignStore, open_campaign
from opentorus.config import default_config
from opentorus.research.dossier import store as dstore
from opentorus.research.dossier.claims import add_claim
from support.campaign import make_engine, make_workspace


def _types(ot_dir: Path, cid: str) -> list[str]:
    events, _ = open_campaign(ot_dir, cid).read_events()
    return [e.type for e in events]


def _snapshot(ot_dir: Path, cid: str) -> CampaignSnapshot:
    return open_campaign(ot_dir, cid).load().snapshot


def _digest(snapshot: CampaignSnapshot) -> dict:
    """Structural digest: everything except wall-clock seconds (excluded by design)."""
    data = snapshot.model_dump(mode="json")
    data["budget"].pop("wall_seconds_used", None)
    for table in ("per_branch", "per_work_item"):
        for entry in data["budget"][table].values():
            entry.pop("wall_seconds", None)
    for branch in data["branches"].values():
        branch["actual_cost"].pop("wall_seconds", None)
    for item in data["work_items"].values():
        item["usage"].pop("wall_seconds", None)
    return data


def test_start_creates_the_campaign_layout(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="exploration", run=False)
    assert record.id == "CAMPAIGN-0001"
    cdir = campaign_dir(ot, pid, record.id)
    for name in ("campaign.yaml", "events.jsonl", "snapshot.json", "progress.md"):
        assert (cdir / name).is_file(), name
    assert (cdir / "branches").is_dir()
    assert _types(ot, record.id) == ["campaign_created"]
    snap = _snapshot(ot, record.id)
    assert snap.phase is CampaignPhase.CREATED and snap.status is CampaignStatus.created
    engine.run(record.id, until=lambda s: s.phase is CampaignPhase.INGEST)
    assert _types(ot, record.id)[:3] == ["campaign_created", "campaign_started", "phase_completed"]
    assert _snapshot(ot, record.id).status is CampaignStatus.running
    progress = (cdir / "progress.md").read_text()
    assert "orchestration state" in progress
    assert "derived from dossier artifacts" in progress


def test_mock_exploration_campaign_runs_to_completed(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="exploration")
    snap = _snapshot(ot, record.id)
    assert snap.phase is CampaignPhase.COMPLETED
    assert snap.status is CampaignStatus.completed
    types = _types(ot, record.id)
    for needed in (
        "campaign_created",
        "campaign_started",
        "problem_normalized",
        "coverage_assessed",
        "branch_proposed",
        "branch_activated",
        "work_item_created",
        "work_item_scheduled",
        "worker_started",
        "worker_completed",
        "budget_consumed",
        "branch_completed",
        "proof_node_created",
        "campaign_completed",
    ):
        assert needed in types, needed
    assert "obligation_closed" not in types
    # The exploration template: numerical, counterexample, literature, special-case —
    # all four kept (initial_branches=4), three activated first, the fourth queued and
    # activated once the literature branch completed. Every branch ends terminal.
    kinds = {b.kind for b in snap.branches.values()}
    assert kinds == {
        BranchKind.numerical,
        BranchKind.counterexample,
        BranchKind.literature,
        BranchKind.special_case,
    }
    assert all(b.status is not BranchStatus.active for b in snap.branches.values())
    literature = next(b for b in snap.branches.values() if b.kind is BranchKind.literature)
    assert literature.root_relation is RootRelation.supporting
    assert literature.assigned_worker_role is WorkerRole.librarian
    assert literature.status is BranchStatus.completed
    assert literature.approach_id is not None and literature.approach_id.startswith("APPR-")
    assert all(b.approach_id for b in snap.branches.values())  # one Approach per branch
    assert snap.coverage_ref is not None and snap.coverage_ref.startswith("COV-")
    # The librarian ran first (literature boost while coverage is insufficient) and was
    # charged the documented one step for an offline work item.
    first = min(snap.work_items.values(), key=lambda wi: wi.work_item_id)
    assert first.role is WorkerRole.librarian
    assert snap.budget.per_work_item[first.work_item_id].steps == 1
    assert snap.rounds >= 4
    # every phase was visited, in table order, at least once
    visited = [p.phase for p in snap.phase_history]
    for phase in (
        CampaignPhase.CREATED,
        CampaignPhase.INGEST,
        CampaignPhase.NORMALIZE,
        CampaignPhase.MAP_LITERATURE,
        CampaignPhase.GENERATE_PORTFOLIO,
        CampaignPhase.SCHEDULE,
        CampaignPhase.EXECUTE,
        CampaignPhase.CRITIQUE,
        CampaignPhase.VERIFY,
        CampaignPhase.UPDATE_GRAPH,
        CampaignPhase.REALLOCATE,
        CampaignPhase.SYNTHESIZE,
        CampaignPhase.COMPLETED,
    ):
        assert phase in visited, phase
    assert visited[:6] == [
        CampaignPhase.CREATED,
        CampaignPhase.INGEST,
        CampaignPhase.NORMALIZE,
        CampaignPhase.MAP_LITERATURE,
        CampaignPhase.GENERATE_PORTFOLIO,
        CampaignPhase.SCHEDULE,
    ]
    assert visited[-2:] == [CampaignPhase.SYNTHESIZE, CampaignPhase.COMPLETED]
    # snapshot == reduce(events)
    store = open_campaign(ot, record.id)
    events, diags = store.read_events()
    assert not diags
    assert reducer.reduce(events).model_dump(mode="json") == json.loads(
        store.snapshot_path.read_text()
    )
    assert store.verify_replay().matches
    # the report was rebuilt and progress written
    assert "report" in (dstore.dossier_dir(ot, pid) / "report.md").read_text().lower()
    assert (campaign_dir(ot, pid, record.id) / "branches" / "BRANCH-0001.md").is_file()


def test_pause_resume_stop_preserve_reasons(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="exploration", run=False)
    engine.run(record.id, until=lambda s: s.phase is CampaignPhase.SCHEDULE)
    assert _snapshot(ot, record.id).phase is CampaignPhase.SCHEDULE
    snap = engine.pause(record.id, "coffee")
    assert snap.status is CampaignStatus.paused
    assert snap.phase is CampaignPhase.PAUSED
    assert snap.pause_reason == "coffee"
    assert snap.resume_phase is CampaignPhase.SCHEDULE
    # pausing twice is idempotent
    assert engine.pause(record.id, "again").pause_reason == "coffee"
    result = engine.resume(record.id)
    assert result.resumed
    assert "schedule" in result.message
    final = _snapshot(ot, record.id)
    assert final.status is CampaignStatus.completed
    types = _types(ot, record.id)
    assert types.count("campaign_paused") == 1 and types.count("campaign_resumed") == 1
    assert types.index("campaign_paused") < types.index("campaign_resumed")

    second = engine.start(pid, mode="exploration", run=False)
    engine.run(second.id, until=lambda s: s.phase is CampaignPhase.INGEST)
    stopped = engine.stop(second.id, "abandoned")
    assert stopped.status is CampaignStatus.stopped
    assert stopped.stop_reason == "abandoned"
    assert stopped.phase is CampaignPhase.STOPPED
    with pytest.raises(Exception, match="already stopped"):
        engine.stop(second.id, "twice")


def test_resume_is_idempotent_on_terminal_campaigns(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    done = engine.start(pid, mode="exploration")
    before = _types(ot, done.id)
    result = engine.resume(done.id)
    assert not result.resumed
    assert "already completed" in result.message
    assert _types(ot, done.id) == before
    stopped = engine.start(pid, mode="exploration", run=False)
    engine.stop(stopped.id, "no")
    result = engine.resume(stopped.id)
    assert not result.resumed and "already stopped" in result.message


def test_budget_exhaustion_pauses_with_reason_and_resume_completes(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="exploration", max_steps=1)
    snap = _snapshot(ot, record.id)
    assert snap.status is CampaignStatus.paused
    assert snap.pause_reason == "BUDGET_EXHAUSTED"
    assert snap.resume_phase is CampaignPhase.REALLOCATE
    assert snap.budget.exhausted == ["steps"]
    types = _types(ot, record.id)
    assert "budget_exhausted" in types and types.index("budget_exhausted") < types.index(
        "campaign_paused"
    )
    store = open_campaign(ot, record.id)
    assert store.verify_replay().matches
    # the paused state is valid and resumable: the completion criterion (budget spent)
    # ends the campaign honestly instead of pausing again forever
    result = engine.resume(record.id)
    assert result.resumed
    final = _snapshot(ot, record.id)
    assert final.status is CampaignStatus.completed
    assert "budget exhausted" in (final.completion_reason or "")
    assert _types(ot, record.id).count("budget_exhausted") == 1


def test_completion_never_touches_claim_statuses_or_problem_status(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    primary = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for all n.")
    add_claim(ot, pid, claim_type="OBSERVATION", statement="P(1) holds numerically.")
    dossier = dstore.require_dossier(ot, pid)
    dossier.primary_claim_id = primary.id
    dstore.save_dossier(ot, dossier)
    before = [(c.id, c.type, c.status) for c in dstore.list_claims(ot, pid)]
    changes_before = len(dstore.list_status_changes(ot, pid))
    dossier_before = dstore.require_dossier(ot, pid)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="prove-or-refute", branches=4)
    assert _snapshot(ot, record.id).status is CampaignStatus.completed
    after = [(c.id, c.type, c.status) for c in dstore.list_claims(ot, pid)]
    assert after == before
    assert len(dstore.list_status_changes(ot, pid)) == changes_before
    dossier_after = dstore.require_dossier(ot, pid)
    assert dossier_after.status == dossier_before.status == "open"
    assert dossier_after.primary_claim_id == primary.id


def test_prove_or_refute_creates_and_designates_primary_claim(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    assert dstore.require_dossier(ot, pid).primary_claim_id is None
    notices: list[str] = []
    engine = make_engine(root, ot, notice=notices.append)
    record = engine.start(pid, mode="prove-or-refute", branches=2, run=False)
    dossier = dstore.require_dossier(ot, pid)
    claims = dstore.list_claims(ot, pid)
    assert len(claims) == 1
    claim = claims[0]
    assert dossier.primary_claim_id == claim.id
    assert claim.type == "CONJECTURE"
    assert claim.status == "unverified"
    assert "P(n)" in claim.statement
    assert dstore.list_status_changes(ot, pid) == []
    assert record.primary_claim_id == claim.id
    assert any(claim.id in n for n in notices)
    types = _types(ot, record.id)
    assert "artifact_created" in types
    events, _ = open_campaign(ot, record.id).read_events()
    created = [e for e in events if e.type == "artifact_created"]
    assert created[0].payload["artifact_id"] == claim.id and created[0].payload["kind"] == "claim"


def test_prove_or_refute_without_primary_claim_refuses_when_asked(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    with pytest.raises(CampaignConfigError) as excinfo:
        engine.start(pid, mode="prove-or-refute", branches=2, create_primary_claim=False)
    assert PRIMARY_CLAIM_REMEDIATION.format(pid=pid) in str(excinfo.value)
    assert dstore.list_claims(ot, pid) == []
    assert not (dstore.dossier_dir(ot, pid) / "campaigns").exists()


def test_prove_or_refute_with_existing_primary_claim_creates_nothing(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    claim = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for all n.")
    dossier = dstore.require_dossier(ot, pid)
    dossier.primary_claim_id = claim.id
    dstore.save_dossier(ot, dossier)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="prove-or-refute", branches=2, run=False)
    assert record.primary_claim_id == claim.id
    assert len(dstore.list_claims(ot, pid)) == 1


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"mode": "nonsense"}, "Unknown campaign mode"),
        ({"mode": "prove-or-refute", "branches": 1}, "at least 2 branches"),
        ({"mode": "exploration", "max_steps": -1}, "--max-steps"),
        ({"mode": "exploration", "cost_budget": -0.5}, "--cost-budget"),
        ({"mode": "exploration", "max_steps": 0}, "--max-steps"),
        ({"mode": "exploration", "branches": 0}, "--branches"),
    ],
)
def test_start_validation_errors(tmp_path: Path, kwargs: dict, needle: str) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    with pytest.raises(CampaignConfigError, match=needle):
        engine.start(pid, **kwargs)
    assert not (dstore.dossier_dir(ot, pid) / "campaigns").exists()


def test_start_requires_an_existing_dossier(tmp_path: Path) -> None:
    root, ot, _pid = make_workspace(tmp_path)
    from opentorus.errors import OpenTorusError

    engine = make_engine(root, ot)
    with pytest.raises(OpenTorusError, match="No problem dossier"):
        engine.start("PROBLEM-0042", mode="exploration")


def test_parallelism_above_one_is_capped_with_a_diagnostic(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    config = default_config()
    config.campaign.max_parallel_workers = 3
    engine = make_engine(root, ot, config=config)
    record = engine.start(pid, mode="exploration", run=False)
    snap = _snapshot(ot, record.id)
    assert [d.kind for d in snap.diagnostics] == ["parallelism_capped"]
    assert "3" in snap.diagnostics[0].message
    assert "parallelism_capped" in _types(ot, record.id)


def test_two_fresh_workspaces_produce_identical_logs_and_digests(tmp_path: Path) -> None:
    results = []
    for name in ("a", "b"):
        root, ot, pid = make_workspace(tmp_path / name)
        engine = make_engine(root, ot, clock=StepClock())
        record = engine.start(pid, mode="exploration")
        results.append((_types(ot, record.id), _digest(_snapshot(ot, record.id))))
    assert results[0][0] == results[1][0]
    assert results[0][1] == results[1][1]


def test_invalid_transition_from_a_handler_records_campaign_failed(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    engine._handlers[CampaignPhase.INGEST] = lambda run: PhaseOutcome(CampaignPhase.EXECUTE, "bad")
    record = engine.start(pid, mode="exploration")
    snap = _snapshot(ot, record.id)
    assert snap.status is CampaignStatus.failed
    assert snap.phase is CampaignPhase.FAILED
    assert "invalid phase transition" in (snap.failure_reason or "")
    assert open_campaign(ot, record.id).verify_replay().matches


def test_keyboard_interrupt_pauses_with_reason_interrupted_and_reraises(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)

    class _Interrupting:
        role = WorkerRole.librarian

        def run(self, ctx: WorkerContext, rt: object) -> WorkerResult:
            raise KeyboardInterrupt

    engine = make_engine(root, ot, worker_registry={WorkerRole.librarian: _Interrupting()})
    with pytest.raises(KeyboardInterrupt):
        engine.start(pid, mode="exploration")
    snap = _snapshot(ot, "CAMPAIGN-0001")
    assert snap.status is CampaignStatus.paused
    assert snap.pause_reason == "interrupted"
    assert snap.resume_phase is CampaignPhase.EXECUTE
    assert (campaign_dir(ot, pid, "CAMPAIGN-0001") / "progress.md").is_file()


def test_missing_worker_role_fails_the_item_honestly(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot, worker_registry={})
    record = engine.start(pid, mode="exploration")
    snap = _snapshot(ot, record.id)
    assert snap.status is CampaignStatus.completed
    types = _types(ot, record.id)
    assert "worker_failed" in types and "branch_exhausted" in types
    item = next(iter(snap.work_items.values()))
    assert item.status.value == "failed"
    assert "no worker registered" in (item.failure_reason or "")


def test_worker_exception_is_a_failed_item_not_a_crash(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)

    class _Boom:
        role = WorkerRole.librarian

        def run(self, ctx: WorkerContext, rt: object) -> WorkerResult:
            raise RuntimeError("kaboom")

    engine = make_engine(root, ot, worker_registry={WorkerRole.librarian: _Boom()})
    record = engine.start(pid, mode="exploration", max_steps=3)
    snap = _snapshot(ot, record.id)
    types = _types(ot, record.id)
    assert "worker_failed" in types
    failed = [wi for wi in snap.work_items.values() if wi.status.value == "failed"]
    assert failed and "kaboom" in (failed[0].failure_reason or "")
    assert snap.branches["BRANCH-0001"].consecutive_failures >= 1
    # the campaign ends (budget or branch budget), never crashes
    assert snap.status in (CampaignStatus.completed, CampaignStatus.paused)


def test_run_can_stop_at_a_predicate_and_continue_later(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="exploration", run=False)
    snap = engine.run(record.id, until=lambda s: s.phase is CampaignPhase.EXECUTE)
    assert snap.phase is CampaignPhase.EXECUTE and snap.status is CampaignStatus.running
    assert snap.current_worker is None
    result = engine.resume(record.id)
    assert result.resumed and "continued" in result.message
    assert _snapshot(ot, record.id).status is CampaignStatus.completed


def test_engine_reads_a_store_written_by_another_engine_instance(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    first = make_engine(root, ot)
    record = first.start(pid, mode="exploration", run=False)
    first.run(record.id, until=lambda s: s.phase is CampaignPhase.SCHEDULE)
    second = CampaignEngine(root, ot, default_config(), clock=StepClock())
    second.pause(record.id, "handover")
    loaded = CampaignStore(ot, pid, record.id).load()
    assert loaded.snapshot.pause_reason == "handover"
    assert not loaded.diagnostics


def test_resume_after_interrupt_fails_the_stale_item_and_completes(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)

    class _InterruptOnce:
        role = WorkerRole.librarian

        def __init__(self) -> None:
            self.calls = 0

        def run(self, ctx: WorkerContext, rt: object) -> WorkerResult:
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            from opentorus.campaign.workers.librarian import LibrarianWorker

            return LibrarianWorker().run(ctx, rt)  # type: ignore[arg-type]

    worker = _InterruptOnce()
    from opentorus.campaign.workers import DEFAULT_WORKERS

    registry = {**DEFAULT_WORKERS, WorkerRole.librarian: worker}
    engine = make_engine(root, ot, worker_registry=registry)
    with pytest.raises(KeyboardInterrupt):
        engine.start(pid, mode="exploration", max_steps=30)
    paused = _snapshot(ot, "CAMPAIGN-0001")
    assert paused.current_worker is None
    running = [wi for wi in paused.work_items.values() if wi.status.value == "running"]
    assert len(running) == 1
    stale = running[0]
    assert stale.role is WorkerRole.librarian  # the librarian is scheduled first
    result = engine.resume("CAMPAIGN-0001")
    assert result.resumed
    final = _snapshot(ot, "CAMPAIGN-0001")
    assert final.status is CampaignStatus.completed
    # the interrupted item is failed on resume, its branch is picked again and completes
    assert final.work_items[stale.work_item_id].status.value == "failed"
    assert "interrupted" in (final.work_items[stale.work_item_id].failure_reason or "")
    literature = final.branches[stale.branch_id]
    assert literature.kind is BranchKind.literature
    assert literature.status is BranchStatus.completed
    assert worker.calls == 2
    assert open_campaign(ot, "CAMPAIGN-0001").verify_replay().matches


def test_paused_created_campaign_gets_campaign_started_on_first_run(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="exploration", run=False)
    engine.pause(record.id, "wait")
    assert _snapshot(ot, record.id).resume_phase is CampaignPhase.CREATED
    result = engine.resume(record.id)
    assert result.resumed
    types = _types(ot, record.id)
    assert types.count("campaign_started") == 1
    final = _snapshot(ot, record.id)
    assert final.started_at is not None and final.status is CampaignStatus.completed
