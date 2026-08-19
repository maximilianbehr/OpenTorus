"""The falsifier: bounded counterexample searches recorded as evidence, never as status.

Target claim: the dossier's designated primary claim when there is one, else one
branch-level *workspace* claim (``research.claims.new_claim(problem_id=…)``) created
on the branch's first run and reported back so the engine stores it on the branch
(``target_claim_id``). Evidence goes through ``math_experiments.record_search_evidence``
— a found witness is strong *contradicting* evidence, a clean bounded search is weak
*supporting* evidence — and never through anything that could move a claim status.

Offline (mock provider) the worker scaffolds the ``counterexample_search`` template
experiment once per branch and runs it. The stock template tests a placeholder
predicate (``n*n >= n``): a run of it is a reproducible scaffold, not evidence about
the claim, so — exactly like ``research.evidence.add_evidence`` refuses to cite an
unmodified template — no evidence is recorded for it and the work item fails with a
``no_witness_found`` signature whose counterargument says why. An experiment whose
predicate *was* edited (by a model in the loop path, or by a human) is parsed and its
result recorded. With a real provider the model designs the search in a bounded loop
(``exp_new`` → edit ``run.py`` → ``exp_run``); the worker then parses every new
experiment's output. Nothing found is a ``no_witness_found`` signature so the branch
is not re-run unchanged.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.failures import build_failure_signature
from opentorus.campaign.models import (
    ArtifactRef,
    CostTotals,
    FailureSignature,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import (
    WorkerRuntime,
    acquire_lease,
    bounded_loop,
    experiment_deliverable,
    experiment_timeout_gate,
    is_mock_provider,
)
from opentorus.errors import OpenTorusError

SEARCH_TEMPLATE = "counterexample_search"
UNMODIFIED_TEMPLATE_NOTE = (
    "the search predicate is the unmodified template (a tautology): the run is a "
    "reproducible scaffold, not evidence about the claim, so no evidence was recorded"
)


def resolve_target_claim(ctx: WorkerContext, rt: WorkerRuntime) -> tuple[str, ArtifactRef | None]:
    """``(claim_id, created_ref)``: the primary claim, the branch's claim, or a new one."""
    from opentorus.research.claims import get_claim, new_claim

    pid = ctx.root_problem.problem_id
    if ctx.root_problem.primary_claim_id:
        return ctx.root_problem.primary_claim_id, None
    if ctx.target_claim_id and get_claim(rt.ot_dir, ctx.target_claim_id) is not None:
        return ctx.target_claim_id, None
    statement = ctx.root_problem.statement.strip() or ctx.root_problem.title or pid
    claim = new_claim(rt.ot_dir, statement, problem_id=pid)
    return claim.id, ArtifactRef(artifact_id=claim.id, kind="claim", branch_id=ctx.branch_id)


def branch_experiments(ctx: WorkerContext, rt: WorkerRuntime) -> list[str]:
    """Workspace experiments this branch already produced (ids, from the context)."""
    from opentorus.research.experiments import get_experiment

    return [
        a
        for a in ctx.branch_artifact_ids
        if a.startswith("EXP-") and get_experiment(rt.ot_dir, a) is not None
    ]


def _stdout(ot_dir: Path, exp_path: str) -> str:
    path = ot_dir / exp_path / "results" / "stdout.txt"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _prompt(ctx: WorkerContext) -> str:
    problem = ctx.root_problem
    lines = [
        f"Counterexample search for {problem.problem_id}.",
        f"Statement: {problem.statement}",
        f"Branch objective: {ctx.branch_objective}",
    ]
    if ctx.assumption_context:
        lines.append("Assumptions: " + "; ".join(ctx.assumption_context))
    lines += [
        "Workflow: exp_new(title=..., template='counterexample_search') creates "
        "experiments/EXP-*/run.py; edit its conjecture_holds predicate and START/STOP "
        "with write_file to encode THIS statement; then exp_run(exp_id=...). Record what "
        "range was searched. A found value is a COUNTEREXAMPLE_CANDIDATE only — say so.",
    ]
    if ctx.failure_signatures:
        lines.append(
            "Do not repeat these failed searches unchanged: "
            + "; ".join(f"{s.tool_or_solver}: {s.counterargument}" for s in ctx.failure_signatures)
        )
    return "\n".join(lines)


class FalsifierWorker:
    role = WorkerRole.falsifier

    def _signature(
        self, ctx: WorkerContext, *, counterargument: str, artifact_ids: list[str]
    ) -> FailureSignature:
        return build_failure_signature(
            role=self.role,
            strategy_class=ctx.strategy_key or "counterexample_search",
            assumption_context=ctx.assumption_context,
            tool_or_solver=SEARCH_TEMPLATE,
            error_category="no_witness_found",
            counterargument=counterargument,
            artifact_ids=artifact_ids,
        )

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.agent.research_iteration import parse_search_result
        from opentorus.research.experiments import (
            get_experiment,
            is_unmodified_counterexample_template,
            new_experiment,
            run_experiment,
        )
        from opentorus.research.math_experiments import record_search_evidence

        pid = ctx.root_problem.problem_id
        try:
            lease = acquire_lease(ctx, rt)
        except OpenTorusError as exc:
            return WorkerResult(
                status="failed",
                error_category="tool_unavailable",
                message=f"no eligible provider: {exc}",
                usage=CostTotals(steps=1),
            )
        artifacts: list[ArtifactRef] = []
        notes: list[str] = []
        claim_id, created = resolve_target_claim(ctx, rt)
        if created is not None:
            artifacts.append(created)
            notes.append(f"branch-level workspace claim {claim_id} created for evidence")
        turns = 0
        exp_ids: list[str] = []
        if is_mock_provider(lease.provider):
            prior = branch_experiments(ctx, rt)
            unrun = [
                e
                for e in prior
                if (x := get_experiment(rt.ot_dir, e)) is not None
                and x.status not in ("completed", "failed")
            ]
            if unrun:
                exp_ids = unrun
            elif prior:
                sig = build_failure_signature(
                    role=self.role,
                    strategy_class=ctx.strategy_key or "counterexample_search",
                    assumption_context=ctx.assumption_context,
                    tool_or_solver=SEARCH_TEMPLATE,
                    error_category="model_no_progress",
                    counterargument=(
                        "offline falsifier: the branch already ran its template search "
                        f"({', '.join(prior)}); no model to design a new one"
                    ),
                    artifact_ids=list(prior),
                )
                return WorkerResult(
                    status="failed",
                    error_category="model_no_progress",
                    message=sig.counterargument,
                    usage=CostTotals(steps=1),
                    routing_decision_id=lease.decision.decision_id,
                    failure_signature=sig,
                    target_claim_id=claim_id,
                    artifacts_created=artifacts,
                )
            else:
                created_exp = new_experiment(
                    rt.ot_dir,
                    f"{ctx.campaign_id} {ctx.branch_id or 'campaign'} counterexample search",
                    template=SEARCH_TEMPLATE,
                    problem_id=pid,
                )
                exp_ids = [created_exp.id]
        else:
            before = {e.id for e in _list_ws_experiments(rt.ot_dir)}
            gate, hint = experiment_deliverable(rt.ot_dir, template=SEARCH_TEMPLATE, before=before)
            timeout_coercions: list[str] = []
            loop = bounded_loop(
                ctx,
                rt,
                lease=lease,
                tool_gate=experiment_timeout_gate(
                    rt.config.campaign.max_experiment_seconds, timeout_coercions
                ),
                session_gate=gate,
                session_recovery_hint=hint,
            )
            loop.run(_prompt(ctx))
            turns = loop.steps_run
            if timeout_coercions:
                notes.append(
                    f"{len(timeout_coercions)} experiment timeout(s) capped at "
                    f"{rt.config.campaign.max_experiment_seconds}s (asked: "
                    f"{', '.join(timeout_coercions)})"
                )
            exp_ids = sorted(e.id for e in _list_ws_experiments(rt.ot_dir) if e.id not in before)
        found = False
        evidence_ids: list[str] = []
        scaffold_only = False
        for exp_id in exp_ids:
            found_exp = get_experiment(rt.ot_dir, exp_id)
            if found_exp is None:
                continue
            exp = found_exp
            if exp.status not in ("completed", "failed"):
                exp, _code = run_experiment(rt.ot_dir, exp_id, timeout=120)
            artifacts.append(
                ArtifactRef(artifact_id=exp.id, kind="experiment", branch_id=ctx.branch_id)
            )
            result = parse_search_result(_stdout(rt.ot_dir, exp.path))
            if result is None:
                notes.append(f"{exp.id}: output carries no counterexample_search result")
                continue
            if is_unmodified_counterexample_template(rt.ot_dir, exp):
                scaffold_only = True
                notes.append(f"{exp.id}: {UNMODIFIED_TEMPLATE_NOTE}")
                continue
            evidence, advisory = record_search_evidence(rt.ot_dir, claim_id, result)
            evidence_ids.append(evidence.id)
            artifacts.append(
                ArtifactRef(artifact_id=evidence.id, kind="evidence", branch_id=ctx.branch_id)
            )
            notes.append(f"{exp.id}: {result.evidence_summary()} -> {evidence.id}")
            if advisory:
                notes.append(advisory)
            found = found or result.found
        usage = CostTotals(steps=max(1, turns))
        if found:
            return WorkerResult(
                status="completed",
                artifacts_created=artifacts,
                usage=usage,
                routing_decision_id=lease.decision.decision_id,
                notes=[
                    *notes,
                    "a witness was found: strong contradicting evidence recorded; "
                    "the claim status is untouched (a COUNTEREXAMPLE_CANDIDATE needs an "
                    "explicit verification record)",
                ],
                target_claim_id=claim_id,
            )
        if scaffold_only:
            counterargument = UNMODIFIED_TEMPLATE_NOTE
        elif exp_ids:
            counterargument = "bounded search found no witness in the searched range"
        else:
            counterargument = f"no search experiment produced in {max(1, turns)} model turn(s)"
        sig = self._signature(
            ctx, counterargument=counterargument, artifact_ids=[*exp_ids, *evidence_ids]
        )
        return WorkerResult(
            status="failed",
            error_category="no_witness_found",
            message=counterargument,
            artifacts_created=artifacts,
            usage=usage,
            routing_decision_id=lease.decision.decision_id,
            notes=notes or [counterargument],
            failure_signature=sig,
            target_claim_id=claim_id,
        )


def _list_ws_experiments(ot_dir: Path):  # noqa: ANN202 - Experiment type imported lazily
    from opentorus.research.experiments import list_experiments

    return list_experiments(ot_dir)


__all__ = [
    "SEARCH_TEMPLATE",
    "UNMODIFIED_TEMPLATE_NOTE",
    "FalsifierWorker",
    "branch_experiments",
    "resolve_target_claim",
]
