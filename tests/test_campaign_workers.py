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


# --------------------------------------------------------------------------------------
# M4 workers: offline behaviour under the mock provider, honest failure signatures
# --------------------------------------------------------------------------------------


def _runtime(root: Path, ot: Path, config=None) -> WorkerRuntime:  # noqa: ANN001
    cfg = config or default_config()
    return WorkerRuntime(
        root=root,
        ot_dir=ot,
        config=cfg,
        pool=ProviderPool(cfg, ot_dir=ot),
        clock=StepClock(),
    )


def _branch_ctx(pid: str, role: WorkerRole, **overrides: object) -> WorkerContext:
    from opentorus.campaign.scheduler import ROLE_TASK_CLASS
    from opentorus.campaign.workers.base import ROLE_ALLOWED_TOOLS

    base: dict[str, object] = {
        "role": role,
        "task_class": ROLE_TASK_CLASS[role].value,
        "budget": WorkBudget(max_steps=8),
        "allowed_tools": ROLE_ALLOWED_TOOLS[role],
        "root_problem": NormalizedProblem(
            problem_id=pid, statement="For every n >= 1, the property P(n) holds."
        ),
    }
    base.update(overrides)
    return _ctx(pid, **base)


def test_prover_bootstraps_a_sketch_and_proposes_obligations_under_mock(tmp_path: Path) -> None:
    from opentorus.campaign.workers.prover import ProverWorker
    from opentorus.research.dossier import store as dstore

    root, ot, pid = make_workspace(tmp_path)
    rt = _runtime(root, ot)
    ctx = _branch_ctx(
        pid,
        WorkerRole.prover,
        branch_objective="Create a clearly labelled informal proof attempt with gaps marked.",
        root_relation="equivalent",
        strategy_key="proof_sketch",
    )
    result = ProverWorker().run(ctx, rt)
    assert result.status == "completed"
    proofs = dstore.list_proof_attempts(ot, pid)
    assert [p.id for p in proofs] == ["PROOF-0001"]
    assert proofs[0].scope == "primary" and proofs[0].status == "sketch"
    assert result.artifacts_created[0].artifact_id == "PROOF-0001"
    assert result.artifacts_created[0].kind == "proof_attempt"
    assert result.obligations, "every explicit gap becomes an obligation proposal"
    for ob in result.obligations:
        assert ob.source_proof_id == "PROOF-0001"
        assert ob.gap_marker
        assert ClosureMode.nl_proof_referee_accepted in ob.closure_modes
        assert ClosureMode.formal_proof in ob.closure_modes
        assert ob.root_relation.value == "equivalent"
    assert result.usage.steps >= 6  # five chat turns, then the bootstrap, then the answer
    assert result.routing_decision_id is not None
    assert dstore.list_status_changes(ot, pid) == []
    # a special-case branch never writes the dossier's primary sketch
    ctx2 = _branch_ctx(
        pid,
        WorkerRole.prover,
        branch_id="BRANCH-0002",
        work_item_id="WI-0002",
        session_id="CAMPAIGN-0001:BRANCH-0002:WI-0002",
        branch_objective="Special cases of PROBLEM-0001: restrict to n <= 10 and n prime.",
        root_relation="special-case",
        strategy_key="special_cases",
    )
    result2 = ProverWorker().run(ctx2, rt)
    assert result2.status == "completed"
    proofs = dstore.list_proof_attempts(ot, pid)
    assert [(p.id, p.scope) for p in proofs] == [
        ("PROOF-0001", "primary"),
        ("PROOF-0002", "exploration"),
    ]
    # a second attempt on the first branch (gap-fill mode) under the mock makes no progress
    ctx3 = ctx.model_copy(
        update={"branch_artifact_ids": ("PROOF-0001",), "work_item_id": "WI-0003"}
    )
    result3 = ProverWorker().run(ctx3, rt)
    assert result3.status == "failed"
    assert result3.error_category == "model_no_progress"
    assert result3.failure_signature is not None
    assert result3.failure_signature.strategy_class == "proof_sketch"
    assert result3.failure_signature.tool_or_solver == "proof_write"
    assert len(dstore.list_proof_attempts(ot, pid)) == 2


def test_falsifier_scaffold_search_records_experiment_but_no_evidence(tmp_path: Path) -> None:
    from opentorus.campaign.workers.falsifier import UNMODIFIED_TEMPLATE_NOTE, FalsifierWorker
    from opentorus.research.claims import list_claims
    from opentorus.research.evidence import list_evidence
    from opentorus.research.experiments import list_experiments

    root, ot, pid = make_workspace(tmp_path)
    rt = _runtime(root, ot)
    ctx = _branch_ctx(pid, WorkerRole.falsifier, strategy_key="counterexample_search")
    result = FalsifierWorker().run(ctx, rt)
    assert result.status == "failed" and result.error_category == "no_witness_found"
    assert result.failure_signature is not None
    assert result.failure_signature.counterargument == UNMODIFIED_TEMPLATE_NOTE
    kinds = [(r.kind, r.artifact_id) for r in result.artifacts_created]
    assert ("claim", "CLAIM-0001") in kinds  # branch-level workspace claim (no primary)
    assert ("experiment", "EXP-0001") in kinds
    assert result.target_claim_id == "CLAIM-0001"
    assert [c.id for c in list_claims(ot)] == ["CLAIM-0001"]
    assert list_experiments(ot)[0].status == "completed"
    assert list_evidence(ot) == []  # a tautology test is not evidence about the claim
    # a second offline attempt on the same branch is an honest no-progress signature
    ctx2 = ctx.model_copy(
        update={"branch_artifact_ids": ("CLAIM-0001", "EXP-0001"), "target_claim_id": "CLAIM-0001"}
    )
    again = FalsifierWorker().run(ctx2, rt)
    assert again.status == "failed" and again.error_category == "model_no_progress"
    assert [c.id for c in list_claims(ot)] == ["CLAIM-0001"]  # the branch claim is reused


def test_falsifier_records_evidence_for_a_real_predicate_and_never_touches_status(
    tmp_path: Path,
) -> None:
    from opentorus.campaign.workers.falsifier import FalsifierWorker
    from opentorus.research.claims import get_claim
    from opentorus.research.dossier import store as dstore
    from opentorus.research.dossier.claims import add_claim
    from opentorus.research.evidence import list_evidence
    from opentorus.research.experiments import new_experiment
    from opentorus.research.math_experiments import MATH_TEMPLATES

    root, ot, pid = make_workspace(tmp_path)
    primary = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for all n.")
    dossier = dstore.require_dossier(ot, pid)
    dossier.primary_claim_id = primary.id
    dstore.save_dossier(ot, dossier)
    # an experiment whose predicate was edited (as a model or a human would): n < 50 fails at 50
    body = MATH_TEMPLATES["counterexample_search"].replace("return n * n >= n", "return n < 50")
    exp = new_experiment(ot, "edited search", run_body=body, problem_id=pid)
    rt = _runtime(root, ot)
    ctx = _branch_ctx(
        pid,
        WorkerRole.falsifier,
        strategy_key="counterexample_search",
        branch_artifact_ids=(exp.id,),
        root_problem=NormalizedProblem(
            problem_id=pid, statement="P(n) for all n.", primary_claim_id=primary.id
        ),
    )
    result = FalsifierWorker().run(ctx, rt)
    assert result.status == "completed"  # a witness was found
    assert result.target_claim_id == primary.id  # the designated primary claim is the target
    evidence = list_evidence(ot, primary.id)
    assert len(evidence) == 1
    assert evidence[0].direction == "contradicts" and evidence[0].strength == "strong"
    assert any(
        r.kind == "evidence" and r.artifact_id == evidence[0].id for r in result.artifacts_created
    )
    # evidence only: neither the dossier claim nor any workspace claim changed status
    assert dstore.get_claim(ot, pid, primary.id).status == "unverified"  # type: ignore[union-attr]
    assert dstore.list_status_changes(ot, pid) == []
    assert get_claim(ot, primary.id) is None  # no workspace claim was created for it


def test_numerical_worker_scaffold_and_edited_experiment(tmp_path: Path) -> None:
    from opentorus.campaign.workers.numerical import NumericalWorker, choose_template
    from opentorus.research.evidence import list_evidence
    from opentorus.research.experiments import new_experiment
    from opentorus.research.math_experiments import MATH_TEMPLATES

    assert choose_template("compute a rigorous interval enclosure") == "validated_numerics"
    assert choose_template("tabulate P(n)") == "numerical"
    root, ot, pid = make_workspace(tmp_path)
    rt = _runtime(root, ot)
    ctx = _branch_ctx(pid, WorkerRole.numerical_experimenter, strategy_key="numerical_experiment")
    result = NumericalWorker().run(ctx, rt)
    assert result.status == "failed" and result.error_category == "model_no_progress"
    assert result.failure_signature is not None
    assert result.failure_signature.tool_or_solver == "numerical"
    assert any(r.kind == "experiment" for r in result.artifacts_created)
    assert list_evidence(ot) == []
    # an edited validated-numerics experiment yields bounds/sampled evidence
    body = MATH_TEMPLATES["validated_numerics"].replace("x * x - x + 1", "x * x - x + 2")
    exp = new_experiment(ot, "edited numerics", run_body=body, problem_id=pid)
    ctx2 = _branch_ctx(
        pid,
        WorkerRole.numerical_experimenter,
        branch_id="BRANCH-0002",
        strategy_key="numerical_experiment",
        branch_objective="rigorous interval bound",
        branch_artifact_ids=(exp.id,),
        target_claim_id=result.target_claim_id,
    )
    result2 = NumericalWorker().run(ctx2, rt)
    assert result2.status == "completed", result2.notes
    assert list_evidence(ot, result.target_claim_id)  # recorded on the branch's claim


def test_symbolic_worker_certificate_or_honest_inconclusive(tmp_path: Path) -> None:
    from opentorus.campaign.workers.symbolic import NO_CERTIFICATE, SymbolicWorker
    from opentorus.research.verifiers.proofs import list_proofs

    root, ot, pid = make_workspace(tmp_path)
    rt = _runtime(root, ot)
    ctx = _branch_ctx(
        pid,
        WorkerRole.symbolic_experimenter,
        strategy_key="symbolic_simplification",
        branch_objective="Rewrite the recurrence into closed form.",
    )
    result = SymbolicWorker().run(ctx, rt)
    assert result.status == "failed" and result.error_category == "verifier_inconclusive"
    assert result.failure_signature is not None
    assert result.failure_signature.counterargument == NO_CERTIFICATE
    assert result.failure_signature.tool_or_solver == "sympy"
    assert list_proofs(ot) == []
    cert = '{"lhs": "sin(x)**2 + cos(x)**2", "rhs": "1", "relation": "eq", "vars": {"x": "real"}}'
    ctx2 = ctx.model_copy(update={"branch_objective": f"Check the identity. certificate: {cert}"})
    result2 = SymbolicWorker().run(ctx2, rt)
    assert result2.status == "completed", result2.notes
    assert [r.kind for r in result2.artifacts_created] == ["proof"]
    assert result2.verifications and result2.verifications[0].accepted
    assert list_proofs(ot)[0].accepted and list_proofs(ot)[0].submitted_under == "CAMPAIGN-0001"
    bad = '{"lhs": "x + 1", "rhs": "x", "relation": "eq", "vars": {"x": "real"}}'
    ctx3 = ctx.model_copy(update={"branch_objective": f"Nope. certificate: {bad}"})
    result3 = SymbolicWorker().run(ctx3, rt)
    assert result3.status == "failed" and result3.error_category == "verifier_rejected"
    assert result3.verifications and not result3.verifications[0].accepted


def test_formalizer_reports_tool_unavailable_or_inconclusive_honestly(tmp_path: Path) -> None:
    from opentorus.campaign.workers.formalizer import FormalizerWorker
    from opentorus.research.verifiers.proofs import list_proofs

    root, ot, pid = make_workspace(tmp_path)
    ctx = _branch_ctx(pid, WorkerRole.formalizer, strategy_key="formalization_attempt")
    result = FormalizerWorker().run(ctx, _runtime(root, ot))
    assert result.status == "failed" and result.error_category == "tool_unavailable"
    assert result.failure_signature is not None
    assert result.failure_signature.tool_or_solver == "formal:none"
    assert result.failure_signature.verifier_backends == []
    assert result.routing_decision_id is None  # no provider was even leased
    config = default_config()
    config.tools.verifiers.smt = True
    result2 = FormalizerWorker().run(ctx, _runtime(root, ot, config))
    assert result2.status == "failed" and result2.error_category == "verifier_inconclusive"
    assert result2.failure_signature is not None
    assert result2.failure_signature.verifier_backends == ["smt"]
    assert "no formal source" in result2.failure_signature.counterargument
    assert list_proofs(ot) == []  # nothing was ever marked checked


def test_critic_records_reviews_and_referee_without_touching_status(tmp_path: Path) -> None:
    from opentorus.agent.review import list_reviews
    from opentorus.campaign.workers.critic import CriticWorker
    from opentorus.research.claims import new_claim
    from opentorus.research.dossier import store as dstore
    from opentorus.research.dossier.claims import add_claim
    from opentorus.research.dossier.referee import latest_referee

    root, ot, pid = make_workspace(tmp_path)
    ws_claim = new_claim(ot, "P(n) holds for all n", problem_id=pid)
    dossier_claim = add_claim(ot, pid, claim_type="CONJECTURE", statement="P(n) for all n.")
    ctx = _ctx(
        pid,
        role=WorkerRole.critic,
        branch_id=None,
        work_item_id=None,
        review_targets=(ws_claim.id, dossier_claim.id, "PROOF-0001"),
    )
    result = CriticWorker().run(ctx, _runtime(root, ot))
    assert result.status == "completed"
    kinds = {r.kind for r in result.reviews}
    assert kinds == {"review", "referee"}
    review = next(r for r in result.reviews if r.kind == "review")
    assert review.target_id == ws_claim.id and review.review_id.startswith("REVIEW-")
    assert list_reviews(ot, ws_claim.id)
    referee = next(r for r in result.reviews if r.kind == "referee")
    assert referee.review_id.startswith("REFEREE-") and latest_referee(ot, pid) is not None
    assert dstore.get_claim(ot, pid, dossier_claim.id).status == "unverified"  # type: ignore[union-attr]
    assert dstore.list_status_changes(ot, pid) == []
    empty = CriticWorker().run(_ctx(pid, role=WorkerRole.critic), _runtime(root, ot))
    assert empty.reviews == [] and "nothing to review" in empty.notes[0]


def test_strategist_uses_the_template_under_mock(tmp_path: Path) -> None:
    from opentorus.campaign.portfolio import PortfolioContext, generate_portfolio
    from opentorus.campaign.workers.strategist import propose_with_model

    root, ot, pid = make_workspace(tmp_path)
    rt = _runtime(root, ot)
    pctx = PortfolioContext(
        campaign_id="CAMPAIGN-0001",
        mode="prove-or-refute",  # type: ignore[arg-type]
        problem=NormalizedProblem(problem_id=pid, statement="P(n)."),
        coverage_insufficient=("definitions_notation",),
    )
    items, notes = propose_with_model(rt, pctx)
    assert items == [] and any("mock provider" in n for n in notes)
    proposal = generate_portfolio(rt, pctx)
    assert proposal.source == "template"
    assert any("mock provider" in n for n in proposal.notes)
    assert len(proposal.accepted) == 4 and len(proposal.rejected) == 3


def test_strategist_parses_a_scripted_provider_answer(tmp_path: Path) -> None:
    from opentorus.campaign.portfolio import PortfolioContext, generate_portfolio

    root, ot, pid = make_workspace(tmp_path)
    answer = (
        "Here is my plan:\n["
        '{"title": "Induction", "kind": "proof", "objective": "prove P(n) by induction on n", '
        '"strategy_summary": "base case then step", "root_relation": "equivalent", '
        '"assumption_context": ["n >= 1"], "why_distinct": "direct route"},'
        '{"title": "Search", "kind": "counterexample", "objective": "search n <= 10^6", '
        '"root_relation": "counterexample-route"},'
        '{"title": "Search twin", "kind": "counterexample", "objective": "search n <= 10^6 too", '
        '"root_relation": "counterexample-route"}'
        "]"
    )
    provider = ScriptedProvider([message(answer)], name="scripted", model_name="m")
    config = default_config()
    rt = WorkerRuntime(
        root=root,
        ot_dir=ot,
        config=config,
        pool=ProviderPool(config, ot_dir=ot, factory=lambda _cfg: provider),
        clock=StepClock(),
    )
    pctx = PortfolioContext(
        campaign_id="CAMPAIGN-0001",
        mode="prove-or-refute",  # type: ignore[arg-type]
        problem=NormalizedProblem(problem_id=pid, statement="P(n)."),
        coverage_insufficient=("definitions_notation",),
        initial_branches=4,
        max_active_branches=3,
    )
    proposal = generate_portfolio(rt, pctx)
    assert proposal.source == "llm"
    kinds = [b.kind.value for b in proposal.accepted]
    assert kinds[:2] == ["proof", "counterexample"]
    assert "literature" in kinds  # forced from the template: coverage insufficient
    assert any(b.rejection_reason == "REPEATED_STRATEGY" for b in proposal.rejected)
    assert proposal.accepted[0].distinctness_note == "direct route"
    assert proposal.accepted[0].assumption_context == ["n >= 1"]
    assert any("template literature branch appended" in n for n in proposal.notes)
    rows = read_usage(ot, session_id="CAMPAIGN-0001:campaign:strategist")
    assert rows and rows[-1].worker_role == "strategist"


def test_executor_worker_context_is_isolated_per_branch(tmp_path: Path) -> None:
    from opentorus.campaign.engine import CampaignEngine
    from opentorus.campaign.models import CampaignPhase
    from opentorus.campaign.store import open_campaign

    root, ot, pid = make_workspace(tmp_path)
    engine = CampaignEngine(root, ot, default_config(), clock=StepClock())
    record = engine.start(pid, mode="prove-or-refute", branches=4, max_steps=40, run=False)
    engine.run(record.id, until=lambda s: s.phase is CampaignPhase.SCHEDULE)
    run = engine._open(record.id)
    snap = run.snap
    branches = sorted(snap.branches.values(), key=lambda b: b.branch_id)
    contexts = [engine._executor.worker_context(run, branch=b) for b in branches]
    sessions = {c.session_id for c in contexts}
    assert len(sessions) == len(contexts)  # every branch its own session id
    for b, c in zip(branches, contexts, strict=True):
        assert c.branch_id == b.branch_id
        assert b.branch_id in c.session_id and record.id in c.session_id
        assert set(c.branch_artifact_ids) <= set(b.artifact_references)
        assert c.allowed_tools  # every model-driven role is restricted
        assert "run_shell" not in c.allowed_tools and "status" not in c.allowed_tools
        assert all(sig.branch_id == b.branch_id for sig in c.failure_signatures)
        assert all(ob.branch_id == b.branch_id for ob in c.open_obligations)
        dumped = c.model_dump(mode="json")
        assert "transcript" not in dumped and "messages" not in dumped
    # shared artifacts are restricted to verified/accepted ones: a fresh campaign has only
    # the coverage assessment
    assert {r.kind for r in contexts[0].shared_artifacts} <= {"coverage"}
    assert open_campaign(ot, record.id).load().snapshot.status.value == "running"
