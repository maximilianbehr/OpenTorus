"""Worker isolation and the verifier-coordinator's closure rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.agent.control.events import ListSink
from opentorus.campaign.clock import StepClock
from opentorus.campaign.models import (
    ClosureMode,
    NormalizedProblem,
    Obligation,
    ObligationStatus,
    WorkBudget,
    WorkerContext,
    WorkerRole,
)
from opentorus.campaign.workers import DEFAULT_WORKERS
from opentorus.campaign.workers.base import (
    WorkerRuntime,
    allowed_tools_gate,
    bounded_loop,
    diff_artifacts,
    snapshot_artifacts,
    usage_tags,
)
from opentorus.campaign.workers.librarian import LibrarianWorker
from opentorus.campaign.workers.verifier import VerifierCoordinatorWorker, closure_candidates
from opentorus.config import default_config
from opentorus.providers.pool import ProviderPool, TaskClass
from opentorus.tools.registry import ToolRegistry
from opentorus.usage import read_usage
from support.campaign import make_workspace
from support.providers import ScriptedProvider, message


def _ctx(pid: str, **overrides: object) -> WorkerContext:
    base: dict[str, object] = {
        "campaign_id": "CAMPAIGN-0001",
        "branch_id": "BRANCH-0001",
        "work_item_id": "WI-0001",
        "role": WorkerRole.prover,
        "task_class": TaskClass.proof_development.value,
        "mode": "prove-or-refute",
        "root_problem": NormalizedProblem(problem_id=pid, statement="For every n, P(n)."),
        "budget": WorkBudget(max_steps=2),
        "session_id": "CAMPAIGN-0001:BRANCH-0001:WI-0001",
        "allowed_tools": frozenset({"status"}),
    }
    base.update(overrides)
    return WorkerContext(**base)  # type: ignore[arg-type]


def test_worker_context_has_no_transcript_fields() -> None:
    from opentorus.agent.session import SessionMessage

    fields = WorkerContext.model_fields
    for name, info in fields.items():
        assert "transcript" not in name and "message" not in name and "history" not in name
        assert "SessionMessage" not in repr(info.annotation)
    ctx = _ctx("PROBLEM-0001", allowed_tools=["b", "a"])
    dumped = ctx.model_dump(mode="json")
    assert dumped["allowed_tools"] == ["a", "b"]  # frozenset serialised sorted
    assert SessionMessage.__name__ not in str(dumped)
    from pydantic import ValidationError

    with pytest.raises(ValidationError):  # frozen
        ctx.session_id = "other"  # type: ignore[misc]


def test_usage_tags_and_allowed_tools_gate() -> None:
    ctx = _ctx("PROBLEM-0001")
    assert usage_tags(ctx) == {
        "campaign_id": "CAMPAIGN-0001",
        "worker_role": "prover",
        "branch_id": "BRANCH-0001",
        "work_item_id": "WI-0001",
    }
    gate = allowed_tools_gate(frozenset({"status"}))
    assert gate is not None
    assert gate("status", {}) is None
    assert "Blocked run_shell" in (gate("run_shell", {}) or "")
    assert allowed_tools_gate(frozenset()) is None


def test_bounded_loop_stamps_campaign_tags_and_routing_id(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    config = default_config()
    provider = ScriptedProvider([message("done.")], name="scripted", model_name="model-x")
    pool = ProviderPool(config, ot_dir=ot, factory=lambda _cfg: provider)
    sink = ListSink()
    rt = WorkerRuntime(
        root=root,
        ot_dir=ot,
        config=config,
        pool=pool,
        clock=StepClock(),
        event_sink=sink,
        registry_factory=lambda _pid: ToolRegistry(),
    )
    ctx = _ctx(pid)
    lease = pool.acquire(
        ctx.task_class, tags={"campaign_id": ctx.campaign_id, "session_id": ctx.session_id}
    )
    loop = bounded_loop(ctx, rt, lease=lease)
    assert loop.max_steps == 2
    assert loop.session_id == ctx.session_id
    answer = loop.run("Say done.")
    assert "done" in answer
    rows = read_usage(ot, session_id=ctx.session_id)
    assert rows, "the loop must record usage under the work item's session"
    row = rows[-1]
    assert row.campaign_id == "CAMPAIGN-0001"
    assert row.branch_id == "BRANCH-0001"
    assert row.work_item_id == "WI-0001"
    assert row.worker_role == "prover"
    assert row.routing_decision_id == lease.decision.decision_id
    assert row.actual_model == "model-x"
    assert any(e.kind == "turn_completed" for e in sink.events)
    assert lease.decision.campaign_id == "CAMPAIGN-0001"


def test_bounded_loop_honours_should_stop(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    config = default_config()
    provider = ScriptedProvider([message("never")], name="scripted")
    pool = ProviderPool(config, ot_dir=ot, factory=lambda _cfg: provider)
    rt = WorkerRuntime(root=root, ot_dir=ot, config=config, pool=pool, should_stop=lambda: True)
    ctx = _ctx(pid)
    lease = pool.acquire(ctx.task_class)
    loop = bounded_loop(ctx, rt, lease=lease, registry=ToolRegistry())
    out = loop.run("go")
    assert "cancelled" in out
    assert provider.calls == []


def test_snapshot_and_diff_artifacts(tmp_path: Path) -> None:
    from opentorus.research.dossier.claims import add_claim

    _root, ot, pid = make_workspace(tmp_path)
    before = snapshot_artifacts(ot, pid)
    add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n).")
    after = snapshot_artifacts(ot, pid)
    refs = diff_artifacts(
        before, after, branch_id="BRANCH-0001", work_item_id="WI-0001", role=WorkerRole.prover
    )
    assert [(r.artifact_id, r.kind) for r in refs] == [("CLAIM-0001", "claim")]
    assert refs[0].branch_id == "BRANCH-0001" and refs[0].role is WorkerRole.prover
    assert snapshot_artifacts(ot, "PROBLEM-0099") == {}


def test_librarian_offline_returns_branch_done_with_coverage(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    rt = WorkerRuntime(
        root=root,
        ot_dir=ot,
        config=default_config(),
        pool=ProviderPool(default_config(), ot_dir=ot),
    )
    result = LibrarianWorker().run(_ctx(pid, role=WorkerRole.librarian, mode="exploration"), rt)
    assert result.status == "branch_done"
    assert result.coverage_ref == "COV-0001"
    assert result.usage.steps == 1
    assert result.insufficient_categories  # a fresh dossier covers nothing
    assert any("partial" in n for n in result.notes)
    assert DEFAULT_WORKERS[WorkerRole.librarian].role is WorkerRole.librarian


def _obligation(**overrides: object) -> Obligation:
    base: dict[str, object] = {
        "obligation_id": "OBL-0001",
        "campaign_id": "CAMPAIGN-0001",
        "branch_id": "BRANCH-0001",
        "statement": "sin(x)^2 + cos(x)^2 = 1",
        "closure_modes": [ClosureMode.formal_proof],
    }
    base.update(overrides)
    return Obligation(**base)  # type: ignore[arg-type]


def test_verifier_closes_nothing_without_an_accepted_artifact(tmp_path: Path) -> None:
    root, ot, pid = make_workspace(tmp_path)
    obligations = [
        _obligation(),
        _obligation(obligation_id="OBL-0002", supporting_artifacts=["PROOF-0042"]),
        _obligation(
            obligation_id="OBL-0003",
            closure_modes=[ClosureMode.accepted_counterexample_certificate],
            supporting_artifacts=["CLAIM-0001"],
        ),
    ]
    proposals, notes = closure_candidates(ot, pid, obligations)
    assert proposals == []
    assert any("no such attempt" in n for n in notes)
    rt = WorkerRuntime(
        root=root,
        ot_dir=ot,
        config=default_config(),
        pool=ProviderPool(default_config(), ot_dir=ot),
    )
    result = VerifierCoordinatorWorker().run(
        _ctx(pid, role=WorkerRole.verifier_coordinator, open_obligations=tuple(obligations)), rt
    )
    assert result.status == "completed" and result.closure_proposals == []
    # with no obligations at all: completed, empty
    empty = VerifierCoordinatorWorker().run(_ctx(pid, role=WorkerRole.verifier_coordinator), rt)
    assert empty.status == "completed" and empty.closure_proposals == []


def test_verifier_proposes_closure_with_an_accepted_proof(tmp_path: Path, accepted_proof) -> None:
    _root, ot, pid = make_workspace(tmp_path)
    proof_id = accepted_proof(ot)
    ob = _obligation(supporting_artifacts=[proof_id], closure_modes=[ClosureMode.formal_proof])
    proposals, _notes = closure_candidates(ot, pid, [ob])
    assert len(proposals) == 1
    p = proposals[0]
    assert p.obligation_id == "OBL-0001"
    assert p.artifact_id == proof_id
    assert p.mode is ClosureMode.formal_proof
    # the specific certificate mode wins when the obligation lists it and the backend matches
    ob2 = _obligation(
        supporting_artifacts=[proof_id],
        closure_modes=[ClosureMode.formal_proof, ClosureMode.exact_symbolic_certificate],
    )
    assert closure_candidates(ot, pid, [ob2])[0][0].mode is ClosureMode.exact_symbolic_certificate
    # a proof recorded under another problem verifies nothing here
    from opentorus.jsonl import rewrite_jsonl
    from opentorus.research.verifiers.proofs import list_proofs, proofs_path

    proofs = list_proofs(ot)
    proofs[-1].problem_id = "PROBLEM-0099"
    rewrite_jsonl(proofs_path(ot), proofs)
    proposals, notes = closure_candidates(ot, pid, [ob])
    assert proposals == [] and any("recorded under PROBLEM-0099" in n for n in notes)
    # closed obligations are skipped
    closed = _obligation(status=ObligationStatus.closed, supporting_artifacts=[proof_id])
    assert closure_candidates(ot, pid, [closed])[0] == []


def test_verifier_never_touches_claim_statuses(tmp_path: Path, accepted_proof) -> None:
    from opentorus.research.dossier import store as dstore
    from opentorus.research.dossier.claims import add_claim

    _root, ot, pid = make_workspace(tmp_path)
    claim = add_claim(ot, pid, claim_type="CONJECTURE", statement="identity")
    proof_id = accepted_proof(ot, claim.id)
    ob = _obligation(supporting_artifacts=[proof_id])
    assert closure_candidates(ot, pid, [ob])[0]
    assert dstore.get_claim(ot, pid, claim.id).status == "unverified"  # type: ignore[union-attr]
    assert dstore.list_status_changes(ot, pid) == []
