"""Real parallel workers: overlap is real, everything else stays as in a sequential run.

A blocking provider proves the overlap (three model calls must be in flight at once or
the barrier times out); the event log keeps one writer, a strict per-item order and a
replay that matches; budgets are reserved before dispatch so concurrent items never
jointly overspend; artifacts are attributed to the work item that created them even
when their writes interleave.
"""

from __future__ import annotations

import threading
from collections import Counter
from pathlib import Path

from opentorus.agent.session import SessionMessage
from opentorus.campaign.concurrency import InFlight
from opentorus.campaign.execution import UsageCollector
from opentorus.campaign.models import (
    BranchStatus,
    CostTotals,
    WorkBudget,
    WorkerContext,
    WorkerResult,
    WorkerRole,
    WorkItemStatus,
)
from opentorus.campaign.store import open_campaign
from opentorus.campaign.workers import DEFAULT_WORKERS
from opentorus.campaign.workers.base import WorkerRuntime, acquire_lease, bounded_loop
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.providers.pool import ProviderPool
from opentorus.tools.registry import ToolRegistry
from support.campaign import make_engine, make_workspace

BRANCH_ROLES = (
    WorkerRole.numerical_experimenter,
    WorkerRole.falsifier,
    WorkerRole.librarian,
    WorkerRole.prover,
)


class BlockingProvider(BaseProvider):
    """The first ``parties`` calls wait for each other at a barrier: if the workers ran
    one at a time the barrier would time out and the test fail."""

    name = "scripted"

    def __init__(self, parties: int) -> None:
        self.barrier = threading.Barrier(parties, timeout=30)
        self.parties = parties
        self._lock = threading.Lock()
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    def generate(self, messages: list[SessionMessage], tools: list[dict] | None = None):  # noqa: ANN201
        if "strategist" in messages[-1].content:
            # the portfolio step runs on the engine thread before any batch; it is not
            # one of the parallel calls (its unparseable answer means: template portfolio)
            return ProviderResponse(kind="message", content="no portfolio")
        with self._lock:
            self.calls += 1
            n = self.calls
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if n <= self.parties:
                self.barrier.wait()
            return ProviderResponse(kind="message", content="done")
        finally:
            with self._lock:
                self.in_flight -= 1


class ModelWorker:
    """One routed model turn through ``bounded_loop``; optionally writes dossier claims
    before and after the model call (to interleave writes across threads)."""

    def __init__(self, role: WorkerRole, *, claims: bool = False, spend_all: bool = False):
        self.role = role
        self.claims = claims
        self.spend_all = spend_all
        self.budgets: list[WorkBudget] = []

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.research.dossier.claims import add_claim

        self.budgets.append(ctx.budget)
        pid = ctx.root_problem.problem_id
        if self.claims:
            add_claim(rt.ot_dir, pid, claim_type="CONJECTURE", statement=f"{ctx.branch_id} before")
        lease = acquire_lease(ctx, rt)
        bounded_loop(ctx, rt, lease=lease, registry=ToolRegistry()).run("think")
        if self.claims:
            add_claim(rt.ot_dir, pid, claim_type="CONJECTURE", statement=f"{ctx.branch_id} after")
        steps = ctx.budget.max_steps if self.spend_all else 1
        return WorkerResult(
            status="branch_done",
            usage=CostTotals(steps=steps),
            routing_decision_id=lease.decision.decision_id,
        )


def _engine(tmp_path: Path, provider: BaseProvider, workers: dict, **campaign: object):  # noqa: ANN202
    root, ot, pid = make_workspace(tmp_path)
    config = default_config()
    config.campaign.max_parallel_workers = 3
    config.campaign.max_total_branches = 0
    for key, value in campaign.items():
        setattr(config.campaign, key, value)
    pool = ProviderPool(config, ot_dir=ot, factory=lambda _cfg: provider)
    engine = make_engine(root, ot, config=config, pool=pool, worker_registry=workers)
    return engine, root, ot, pid


def test_three_workers_overlap_and_the_log_stays_single_writer(tmp_path: Path) -> None:
    provider = BlockingProvider(parties=3)
    workers = {**DEFAULT_WORKERS, **{r: ModelWorker(r) for r in BRANCH_ROLES}}
    # steps are reserved per item (its branch budget), so 3 x 3 fit into 20
    engine, _root, ot, pid = _engine(tmp_path, provider, workers, branch_step_budget=3)
    record = engine.start(pid, mode="exploration", max_steps=20)
    store = open_campaign(ot, record.id)
    snap = store.load().snapshot
    events, diags = store.read_events()
    assert not diags
    assert provider.max_in_flight >= 3, "three model calls were in flight at once"
    assert snap.status.value == "completed"
    assert all(b.status is not BranchStatus.active for b in snap.branches.values())
    # the first batch: three items on three distinct branches, all started before any
    # result was recorded, and each item's events in the fixed per-item order
    starts = [e for e in events if e.type == "worker_started"]
    first_done = next(e.seq for e in events if e.type in ("worker_completed", "worker_failed"))
    batch = [e.work_item_id for e in starts if e.seq < first_done]
    assert len(batch) == 3
    assert len({snap.work_items[w].branch_id for w in batch}) == 3
    for wid in snap.work_items:
        mine = [e.type for e in events if e.work_item_id == wid]
        assert mine.index("work_item_created") < mine.index("worker_started")
        assert mine.index("worker_started") < mine.index("worker_completed")
        assert mine.index("worker_completed") < mine.index("budget_consumed")
        assert snap.work_items[wid].status is WorkItemStatus.completed
    # seq strictly increasing with no gaps: one writer
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    # per-work-item usage: one turn each, the ledger sums them, each item its own route
    for wid, totals in snap.budget.per_work_item.items():
        assert totals.steps == 1, wid
    strategist = sum(
        int(e.payload["steps"])  # type: ignore[call-overload]
        for e in events
        if e.type == "budget_consumed" and e.payload.get("scope") == "model_invocation"
    )
    assert snap.budget.steps_used == len(snap.work_items) + strategist
    routes = [snap.work_items[w].routing_decision_id for w in snap.work_items]
    assert len(set(routes)) == len(routes)
    assert store.verify_replay().matches
    # the campaign wall clock is charged the batch once, not once per concurrent item
    assert snap.budget.wall_seconds_used <= sum(
        t.wall_seconds for t in snap.budget.per_work_item.values()
    )


def test_steps_are_reserved_before_dispatch(tmp_path: Path) -> None:
    provider = BlockingProvider(parties=2)
    workers = {**DEFAULT_WORKERS, **{r: ModelWorker(r, spend_all=True) for r in BRANCH_ROLES}}
    engine, _root, ot, pid = _engine(tmp_path, provider, workers, branch_step_budget=2)
    record = engine.start(pid, mode="exploration", max_steps=3)
    snap = open_campaign(ot, record.id).load().snapshot
    first = sorted(snap.work_items.values(), key=lambda w: w.work_item_id)[:2]
    # 3 steps left, 2 per branch: the first item reserves 2, the second gets the last 1,
    # and no third item is dispatched although three branches are active
    assert [w.budget.max_steps for w in first if w.budget] == [2, 1]
    assert snap.budget.steps_used <= 3
    assert open_campaign(ot, record.id).verify_replay().matches


def test_token_and_cost_budgets_are_split_and_checked_live(tmp_path: Path) -> None:
    from opentorus.campaign.engine import CampaignEngine

    provider = BlockingProvider(parties=1)
    workers = {**DEFAULT_WORKERS, **{r: ModelWorker(r) for r in BRANCH_ROLES}}
    engine, _root, ot, pid = _engine(tmp_path, provider, workers, branch_step_budget=3)
    assert isinstance(engine, CampaignEngine)
    record = engine.start(pid, mode="exploration", max_steps=20, token_budget=60000, run=False)
    run = engine._open(record.id)
    executor = engine._executor
    mine = UsageCollector(None)
    other = UsageCollector(None)
    inflight = InFlight()
    inflight.register("WI-0001", mine)
    inflight.register("WI-0002", other)
    rt = executor.runtime(
        run,
        collector=mine,
        inflight=inflight,
        item_budget=WorkBudget(max_steps=5, tokens_remaining=300),
    )
    assert rt.should_stop is not None and not rt.should_stop()
    mine.tokens = 300  # this item's reserved share is spent
    assert rt.should_stop()
    mine.tokens = 100
    other.tokens = 59950  # jointly over the campaign's 60000 tokens
    assert rt.should_stop()
    other.tokens = 0
    inflight.cancelled.set()  # Ctrl-C on the engine thread
    assert rt.should_stop()
    # and the scheduler hands out equal shares of what is left
    engine.run(record.id)
    snap = open_campaign(ot, record.id).load().snapshot
    first = sorted(snap.work_items.values(), key=lambda w: w.work_item_id)
    events, _ = open_campaign(ot, record.id).read_events()
    first_start = next(e.seq for e in events if e.type == "worker_started")
    before = sum(
        int(e.payload["tokens"])  # type: ignore[call-overload]
        for e in events
        if e.type == "budget_consumed" and e.seq < first_start
    )
    batch = [w for w in first if w.created_seq < first_start]
    shares = {w.budget.tokens_remaining for w in batch if w.budget}
    assert len(batch) == 3 and len(shares) == 1
    (share,) = shares
    assert share is not None and share == (60000 - before) // 3


def test_interleaved_writes_are_attributed_to_the_item_that_made_them(tmp_path: Path) -> None:
    from opentorus.research.dossier import store as dstore

    provider = BlockingProvider(parties=3)
    workers = {**DEFAULT_WORKERS, **{r: ModelWorker(r, claims=True) for r in BRANCH_ROLES}}
    engine, _root, ot, pid = _engine(tmp_path, provider, workers, branch_step_budget=3)
    record = engine.start(pid, mode="exploration", max_steps=20)
    snap = open_campaign(ot, record.id).load().snapshot
    claim_refs = [r for r in snap.artifact_refs if r.kind == "claim"]
    assert len(claim_refs) == 2 * len(snap.work_items)
    claims = {c.id: c for c in dstore.list_claims(ot, pid)}
    for ref in claim_refs:
        claim = claims.get(ref.artifact_id)
        assert claim is not None
        # the claim text names the branch that wrote it: attribution is exact even
        # though the before/after writes of three items interleaved
        assert claim.statement.startswith(ref.branch_id or "?"), (ref, claim.statement)
        assert snap.work_items[ref.work_item_id or ""].branch_id == ref.branch_id
    per_item = Counter(r.work_item_id for r in claim_refs)
    assert set(per_item.values()) == {2}


def test_mock_campaigns_run_in_parallel_with_the_real_workers(tmp_path: Path) -> None:
    """The shipped workers under the mock, three at a time: every mode completes, the
    replay matches, nothing is closed or promoted, and each artifact is attributed to
    exactly one work item."""
    from opentorus.research.dossier import store as dstore

    for mode in ("prove-or-refute", "exploration", "survey"):
        root, ot, pid = make_workspace(tmp_path / mode)
        config = default_config()
        config.campaign.max_parallel_workers = 3
        config.campaign.branch_step_budget = 4
        engine = make_engine(root, ot, config=config)
        record = engine.start(pid, mode=mode, max_steps=40)
        store = open_campaign(ot, record.id)
        snap = store.load().snapshot
        events, diags = store.read_events()
        assert not diags, mode
        assert snap.status.value == "completed", (mode, snap.completion_reason)
        assert store.verify_replay().matches, mode
        assert "obligation_closed" not in {e.type for e in events}
        assert dstore.list_status_changes(ot, pid) == []
        assert snap.budget.steps_used <= 40
        owners = Counter(r.artifact_id for r in snap.artifact_refs if r.work_item_id is not None)
        assert all(n == 1 for n in owners.values()), owners
        if mode != "survey":
            outcomes = [
                str(e.payload.get("outcome", "")) for e in events if e.type == "phase_completed"
            ]
            assert any("in parallel" in o for o in outcomes), mode


def test_one_worker_stays_the_sequential_path(tmp_path: Path) -> None:
    """max_parallel_workers == 1 (the default) never builds a batch."""
    root, ot, pid = make_workspace(tmp_path)
    engine = make_engine(root, ot)
    record = engine.start(pid, mode="exploration")
    events, _ = open_campaign(ot, record.id).read_events()
    assert not any("in parallel" in str(e.payload.get("outcome", "")) for e in events)
    starts = [e.seq for e in events if e.type == "worker_started"]
    ends = [e.seq for e in events if e.type in ("worker_completed", "worker_failed")]
    # strictly alternating: each item finishes before the next starts
    assert all(s < e < n for s, e, n in zip(starts, ends, starts[1:], strict=False))
