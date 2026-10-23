"""Running several work items at once without giving up what the sequential engine
guarantees.

Work in a campaign is I/O bound on the model server, so concurrency is threads, and
the design keeps everything *except the model call* serialized:

* :class:`ConcurrencyGate` is one lock a work item's thread holds for its whole run and
  releases only while it waits for the provider (:class:`GatedProvider`) or for a
  long experiment (``exp_run``, see :func:`gate_experiment_tool`). Tool executions,
  dossier writes, id minting in the ledgers, session and usage-ledger appends, routing
  decisions -- all of it happens under the lock, one thread at a time, exactly as in a
  sequential run. Only the waiting overlaps.
* Because every write happens while exactly one thread holds the lock, the gate can
  attribute artifacts *exactly*: each hold is a segment, and whatever appeared in the
  dossier/workspace ledgers between a segment's start and end was created by that
  segment's work item (:meth:`ConcurrencyGate.attributed`). A worker that inspects
  "what is new since I started" asks :meth:`ConcurrencyGate.foreign` to drop what a
  sibling created or touched in the meantime.
* The event log keeps a single writer: worker threads never append; the engine thread
  records every result after the batch, in scheduled order (the store's append is also
  locked, belt and braces).
* Budgets are reserved before dispatch (steps exactly; tokens and cost as equal shares
  of what is left) and checked live against the spend of every in-flight work item
  (:class:`InFlight`), so concurrent workers cannot jointly overspend a shared budget by
  more than the one model turn each may already be waiting on.

``max_parallel_workers == 1`` never reaches this module: the sequential path is
unchanged and deterministic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from opentorus.campaign.models import ArtifactRef, BudgetLedger, WorkerRole
from opentorus.tools.base import Tool, ToolCall, ToolResult

# Roles whose own "what did I create" bookkeeping is not foreign-aware (the formalizer
# is owned elsewhere): they run alone, never next to another work item.
EXCLUSIVE_ROLES: frozenset[WorkerRole] = frozenset({WorkerRole.formalizer})
# Tools that wait on a subprocess and write only inside their own experiment directory:
# they release the gate while they run so a half-hour experiment does not stall the
# other branches' tool calls.
LOCK_RELEASING_TOOLS: frozenset[str] = frozenset({"exp_run", "run_experiment"})


def _proof_attempt_stamps(ot_dir: Path, problem_id: str) -> dict[str, str]:
    from opentorus.research.dossier import store

    try:
        return {p.id: str(p.updated_at) for p in store.list_proof_attempts(ot_dir, problem_id)}
    except Exception:  # noqa: BLE001 - a broken ledger must not stop attribution
        return {}


class ConcurrencyGate:
    """The work lock plus exact per-work-item artifact attribution (see module doc)."""

    def __init__(self, ot_dir: Path, problem_id: str) -> None:
        self.ot_dir = ot_dir
        self.problem_id = problem_id
        self._lock = threading.Lock()
        self._book = threading.Lock()
        self._local = threading.local()
        self._created: dict[str, list[ArtifactRef]] = {}
        self._owner: dict[str, str] = {}
        self._toucher: dict[str, str] = {}
        self.max_concurrent_waits = 0
        self._waiting = 0

    # -- segments ---------------------------------------------------------------------

    def _index(self) -> tuple[dict[str, set[str]], dict[str, str]]:
        from opentorus.campaign.workers.base import snapshot_artifacts

        return (
            snapshot_artifacts(self.ot_dir, self.problem_id),
            _proof_attempt_stamps(self.ot_dir, self.problem_id),
        )

    def _start(self) -> None:
        self._local.before = self._index()

    def _end(self) -> None:
        item = getattr(self._local, "item", None)
        before = getattr(self._local, "before", None)
        if item is None or before is None:
            return
        ids_before, stamps_before = before
        ids_after, stamps_after = self._index()
        with self._book:
            created = self._created.setdefault(item, [])
            for kind in sorted(ids_after):
                for aid in sorted(ids_after[kind] - ids_before.get(kind, set())):
                    if aid in self._owner:
                        continue
                    self._owner[aid] = item
                    created.append(ArtifactRef(artifact_id=aid, kind=kind))
            for aid, stamp in stamps_after.items():
                if stamps_before.get(aid) != stamp:
                    self._toucher[aid] = item
        self._local.before = None

    def holding(self) -> bool:
        return bool(getattr(self._local, "held", False))

    @contextmanager
    def hold(self, work_item_id: str) -> Iterator[None]:
        """Run a work item's thread under the lock (released only by :meth:`released`)."""
        self._lock.acquire()
        self._local.item = work_item_id
        self._local.held = True
        self._start()
        try:
            yield
        finally:
            try:
                self._end()
            finally:
                self._local.held = False
                self._local.item = None
                self._lock.release()

    @contextmanager
    def released(self) -> Iterator[None]:
        """Let the other work items run while this thread waits (model call, experiment).
        A no-op on a thread that does not hold the gate."""
        if not self.holding():
            yield
            return
        self._end()
        self._local.held = False
        with self._book:
            self._waiting += 1
            self.max_concurrent_waits = max(self.max_concurrent_waits, self._waiting)
        self._lock.release()
        try:
            yield
        finally:
            self._lock.acquire()
            with self._book:
                self._waiting -= 1
            self._local.held = True
            self._start()

    # -- attribution ------------------------------------------------------------------

    def attributed(self, work_item_id: str) -> list[ArtifactRef]:
        """Artifacts that appeared while ``work_item_id`` held the gate, in order."""
        with self._book:
            return list(self._created.get(work_item_id, []))

    def foreign(self, work_item_id: str) -> Callable[[str], bool]:
        """``is_foreign(artifact_id)``: created or last touched by *another* work item
        of this batch."""

        def is_foreign(artifact_id: str) -> bool:
            with self._book:
                owner = self._owner.get(artifact_id)
                toucher = self._toucher.get(artifact_id)
            return (owner is not None and owner != work_item_id) or (
                toucher is not None and toucher != work_item_id
            )

        return is_foreign


class GatedProvider:
    """A provider proxy whose model calls release the gate; everything else forwards."""

    def __init__(self, inner: Any, gate: ConcurrencyGate) -> None:
        self.__dict__["_inner"] = inner
        self.__dict__["_gate"] = gate

    def respond(self, *args: Any, **kwargs: Any) -> Any:
        with self._gate.released():
            return self._inner.respond(*args, **kwargs)

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        with self._gate.released():
            return self._inner.generate(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)


class GatedPool:
    """A provider-pool proxy whose leases carry :class:`GatedProvider` s."""

    def __init__(self, inner: Any, gate: ConcurrencyGate) -> None:
        self._inner = inner
        self._gate = gate

    def acquire(self, *args: Any, **kwargs: Any) -> Any:
        lease = self._inner.acquire(*args, **kwargs)
        return replace(lease, provider=GatedProvider(lease.provider, self._gate))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _GatedTool(Tool):
    """A tool proxy that runs its call with the gate released."""

    def __init__(self, inner: Tool, gate: ConcurrencyGate) -> None:
        self._inner = inner
        self._gate = gate
        self.name = inner.name
        self.description = inner.description
        self.input_schema = inner.input_schema
        self.risk_level = inner.risk_level
        self.permission = inner.permission

    def run(self, call: ToolCall) -> ToolResult:
        with self._gate.released():
            return self._inner.run(call)


def gate_experiment_tool(tool: Tool, gate: ConcurrencyGate | None) -> Tool:
    """``tool`` itself, or a gate-releasing proxy for :data:`LOCK_RELEASING_TOOLS`."""
    if gate is None or tool.name not in LOCK_RELEASING_TOOLS:
        return tool
    return _GatedTool(tool, gate)


@dataclass
class InFlight:
    """The live spend of every work item of a parallel batch (for budget checks)."""

    collectors: dict[str, Any] = field(default_factory=dict)
    cancelled: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def register(self, work_item_id: str, collector: Any) -> None:
        with self._lock:
            self.collectors[work_item_id] = collector

    def totals(self) -> tuple[int, int, float]:
        """``(turns, tokens, cost_usd)`` spent so far by the in-flight work items."""
        with self._lock:
            items = list(self.collectors.values())
        return (
            sum(c.turns for c in items),
            sum(c.tokens for c in items),
            sum(c.cost_usd for c in items),
        )

    def projected(self, ledger: BudgetLedger) -> BudgetLedger:
        """``ledger`` plus the in-flight spend (what the ledger will say once recorded)."""
        from opentorus.campaign.budget import charge

        turns, tokens, cost = self.totals()
        return charge(ledger, "campaign", "", steps=turns, tokens=tokens, cost_usd=cost)


__all__ = [
    "EXCLUSIVE_ROLES",
    "LOCK_RELEASING_TOOLS",
    "ConcurrencyGate",
    "GatedPool",
    "GatedProvider",
    "InFlight",
    "gate_experiment_tool",
]
