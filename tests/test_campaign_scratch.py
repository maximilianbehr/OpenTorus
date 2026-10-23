"""Per-branch scratch directories: each branch writes its own, reads its siblings'."""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.clock import StepClock
from opentorus.campaign.models import (
    CostTotals,
    NormalizedProblem,
    WorkBudget,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.scheduler import ROLE_TASK_CLASS
from opentorus.campaign.workers.base import (
    ROLE_ALLOWED_TOOLS,
    WorkerRuntime,
    bounded_loop,
    scratch_block,
    scratch_write_gate,
)
from opentorus.config import default_config
from opentorus.providers.pool import ProviderPool
from opentorus.tools.builtin import build_default_registry
from support.campaign import make_engine, make_workspace
from support.providers import ScriptedProvider, message, tool_call

WORK = ".opentorus/problems/PROBLEM-0001/work/CAMPAIGN-0001"


def _ctx(pid: str, **kw: object) -> WorkerContext:
    base: dict[str, object] = {
        "campaign_id": "CAMPAIGN-0001",
        "branch_id": "BRANCH-0001",
        "work_item_id": "WI-0001",
        "role": WorkerRole.falsifier,
        "task_class": ROLE_TASK_CLASS[WorkerRole.falsifier].value,
        "mode": "exploration",
        "root_problem": NormalizedProblem(problem_id=pid, statement="For every n, P(n)."),
        "budget": WorkBudget(max_steps=3),
        "session_id": "CAMPAIGN-0001:BRANCH-0001:WI-0001",
        "allowed_tools": ROLE_ALLOWED_TOOLS[WorkerRole.falsifier],
        "work_dir": f"{WORK}/BRANCH-0001",
        "work_root": WORK,
    }
    base.update(kw)
    return WorkerContext(**base)  # type: ignore[arg-type]


class _Recorder:
    def __init__(self, role: WorkerRole) -> None:
        self.role = role
        self.contexts: list[WorkerContext] = []

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        self.contexts.append(ctx)
        return WorkerResult(status="branch_done", usage=CostTotals(steps=1))


def test_each_branch_work_item_gets_its_own_scratch_directory(tmp_path: Path) -> None:
    from opentorus.campaign.workers import DEFAULT_WORKERS

    root, ot, pid = make_workspace(tmp_path)
    recorders = {
        role: _Recorder(role)
        for role in (
            WorkerRole.numerical_experimenter,
            WorkerRole.falsifier,
            WorkerRole.librarian,
            WorkerRole.prover,
        )
    }
    engine = make_engine(root, ot, worker_registry={**DEFAULT_WORKERS, **recorders})
    engine.start(pid, mode="exploration", max_steps=20)
    contexts = [c for r in recorders.values() for c in r.contexts]
    assert len({c.branch_id for c in contexts}) >= 3
    for ctx in contexts:
        assert ctx.work_dir == f"{WORK}/{ctx.branch_id}"
        assert ctx.work_root == WORK
        assert (root / ctx.work_dir).is_dir()
        assert ctx.work_dir in "\n".join(scratch_block(ctx))
    assert len({c.work_dir for c in contexts}) == len({c.branch_id for c in contexts})


def test_sibling_scratch_dirs_are_readable_not_writable(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    config = default_config()
    config.permissions.mode = "trusted"
    sibling = root / WORK / "BRANCH-0002"
    sibling.mkdir(parents=True)
    (sibling / "lemma.md").write_text("their note\n", encoding="utf-8")
    registry = build_default_registry(root, ot, config)
    ctx = _ctx(pid)
    gate = scratch_write_gate(root, ctx, registry)
    assert gate is not None
    assert gate("write_file", {"path": f"{WORK}/BRANCH-0002/x.md"}) is not None
    assert gate("write_file", {"path": f"{WORK}/BRANCH-0001/../BRANCH-0002/x.md"}) is not None
    assert gate("write_file", {"path": f"{WORK}/BRANCH-0001/notes.md"}) is None
    assert gate("write_file", {"path": "notes/elsewhere.md"}) is None
    assert gate("read_file", {"path": f"{WORK}/BRANCH-0002/lemma.md"}) is None
    assert scratch_write_gate(root, _ctx(pid, work_dir="", work_root=""), registry) is None

    provider = ScriptedProvider(
        [
            tool_call("write_file", {"path": f"{WORK}/BRANCH-0002/lemma.md", "content": "mine"}),
            tool_call("read_file", {"path": f"{WORK}/BRANCH-0002/lemma.md"}),
            tool_call("write_file", {"path": f"{WORK}/BRANCH-0001/notes.md", "content": "ok"}),
            message("done"),
        ],
        name="scripted",
    )
    rt = WorkerRuntime(
        root=root,
        ot_dir=ot,
        config=config,
        pool=ProviderPool(config, ot_dir=ot, factory=lambda _cfg: provider),
        clock=StepClock(),
        registry_factory=lambda _pid: build_default_registry(root, ot, config),
    )
    loop = bounded_loop(_ctx(pid, budget=WorkBudget(max_steps=5)), rt, lease=rt.pool.acquire("x"))
    loop.run("go")
    assert (sibling / "lemma.md").read_text(encoding="utf-8") == "their note\n"
    assert (root / WORK / "BRANCH-0001" / "notes.md").read_text(encoding="utf-8") == "ok"
    # the read of the sibling's note came back to the model
    seen = "\n".join(m.content for m in provider.calls[-1][0])
    assert "their note" in seen and "another branch's scratch directory" in seen
