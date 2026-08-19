"""The numerical experimenter: reproducible computations recorded as evidence.

Template: ``validated_numerics`` when the branch objective asks for rigor (interval,
validated, enclosure, bound), else ``numerical``. Evidence is recorded with
``math_experiments.record_bounds_evidence`` when the output parses to a rigorous
enclosure or a sampled estimate, and as weak neutral experiment evidence (through
``research.evidence.add_evidence``, citing the EXP id) for a plain numerical run —
never as anything that could move a claim status.

Offline (mock provider) the worker scaffolds the template experiment once per branch
and runs it. The stock templates compute placeholder quantities unrelated to the
claim (a seeded mean; ``x² − x + 1`` on ``[0, 1]``), so a run of an *unmodified*
template records the EXP artifact but no evidence and fails with a
``model_no_progress`` signature that says so; a template a model or human edited is
parsed and recorded. With a real provider the model designs the computation in a
bounded loop (``exp_new`` → edit ``run.py`` → ``exp_run``) and every new experiment's
output is parsed afterwards.
"""

from __future__ import annotations

import re
from pathlib import Path

from opentorus.campaign.failures import build_failure_signature
from opentorus.campaign.models import (
    ArtifactRef,
    CostTotals,
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
from opentorus.campaign.workers.falsifier import (
    branch_experiments,
    resolve_target_claim,
)
from opentorus.errors import OpenTorusError

_RIGOR = re.compile(r"\b(interval|validated|rigorous|enclosure|bound)\b", re.IGNORECASE)


def choose_template(objective: str) -> str:
    return "validated_numerics" if _RIGOR.search(objective or "") else "numerical"


def template_unmodified(ot_dir: Path, exp_path: str, template: str) -> bool:
    from opentorus.research.math_experiments import MATH_TEMPLATES

    path = ot_dir / exp_path / "run.py"
    if not path.is_file():
        return False
    return path.read_text(encoding="utf-8") == MATH_TEMPLATES.get(template, "")


def _stdout(ot_dir: Path, exp_path: str) -> str:
    path = ot_dir / exp_path / "results" / "stdout.txt"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _prompt(ctx: WorkerContext, template: str) -> str:
    problem = ctx.root_problem
    lines = [
        f"Numerical experiment for {problem.problem_id}.",
        f"Statement: {problem.statement}",
        f"Branch objective: {ctx.branch_objective}",
        f"Workflow: exp_new(title=..., template='{template}') creates "
        "experiments/EXP-*/run.py; edit it with write_file so it computes a quantity that "
        "bears on THIS statement (fixed seed, print one JSON line); then exp_run(exp_id=...). "
        "Results are evidence, never proof.",
    ]
    if ctx.assumption_context:
        lines.append("Assumptions: " + "; ".join(ctx.assumption_context))
    return "\n".join(lines)


class NumericalWorker:
    role = WorkerRole.numerical_experimenter

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.research.evidence import add_evidence
        from opentorus.research.experiments import (
            get_experiment,
            list_experiments,
            new_experiment,
            run_experiment,
        )
        from opentorus.research.math_experiments import parse_numeric_result, record_bounds_evidence

        pid = ctx.root_problem.problem_id
        template = choose_template(ctx.branch_objective)
        strategy = ctx.strategy_key or "numerical_experiment"
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
        exp_ids: list[str]
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
                    strategy_class=strategy,
                    assumption_context=ctx.assumption_context,
                    tool_or_solver=template,
                    error_category="model_no_progress",
                    counterargument=(
                        "offline numerical worker: the branch already ran its template "
                        f"experiment ({', '.join(prior)}); no model to design a new one"
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
                    f"{ctx.campaign_id} {ctx.branch_id or 'campaign'} {template}",
                    template=template,
                    problem_id=pid,
                )
                exp_ids = [created_exp.id]
        else:
            before = {e.id for e in list_experiments(rt.ot_dir)}
            gate, hint = experiment_deliverable(rt.ot_dir, template=template, before=before)
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
            loop.run(_prompt(ctx, template))
            turns = loop.steps_run
            if timeout_coercions:
                notes.append(
                    f"{len(timeout_coercions)} experiment timeout(s) capped at "
                    f"{rt.config.campaign.max_experiment_seconds}s (asked: "
                    f"{', '.join(timeout_coercions)})"
                )
            exp_ids = sorted(e.id for e in list_experiments(rt.ot_dir) if e.id not in before)
        recorded: list[str] = []
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
            if template_unmodified(rt.ot_dir, exp.path, template):
                scaffold_only = True
                notes.append(
                    f"{exp.id}: unmodified {template} template computes a placeholder "
                    "quantity; no evidence recorded"
                )
                continue
            stdout = _stdout(rt.ot_dir, exp.path)
            parsed = parse_numeric_result(stdout)
            if parsed is not None:
                evidence, _advisory = record_bounds_evidence(rt.ot_dir, claim_id, parsed)
                notes.append(f"{exp.id}: bounds evidence {evidence.id}")
            else:
                first = next((ln for ln in stdout.splitlines() if ln.strip()), "").strip()
                evidence, _advisory = add_evidence(
                    rt.ot_dir,
                    claim_id,
                    source_type="experiment",
                    source_id=exp.id,
                    summary=(first[:200] or f"{exp.id} ran ({exp.status})"),
                    direction="neutral",
                    strength="weak",
                    limitations=["single numerical run", "not a proof"],
                    problem_id=pid,
                )
                notes.append(f"{exp.id}: numerical evidence {evidence.id} (weak, neutral)")
            recorded.append(evidence.id)
            artifacts.append(
                ArtifactRef(artifact_id=evidence.id, kind="evidence", branch_id=ctx.branch_id)
            )
        usage = CostTotals(steps=max(1, turns))
        if recorded:
            return WorkerResult(
                status="completed",
                artifacts_created=artifacts,
                usage=usage,
                routing_decision_id=lease.decision.decision_id,
                notes=notes,
                target_claim_id=claim_id,
            )
        counterargument = (
            "unmodified template experiment: placeholder computation, no claim-specific evidence"
            if scaffold_only
            else f"no experiment with parseable output produced in {max(1, turns)} model turn(s)"
        )
        return WorkerResult(
            status="failed",
            error_category="model_no_progress",
            message=counterargument,
            artifacts_created=artifacts,
            usage=usage,
            routing_decision_id=lease.decision.decision_id,
            notes=notes or [counterargument],
            failure_signature=build_failure_signature(
                role=self.role,
                strategy_class=strategy,
                assumption_context=ctx.assumption_context,
                tool_or_solver=template,
                error_category="model_no_progress",
                counterargument=counterargument,
                artifact_ids=list(exp_ids),
            ),
            target_claim_id=claim_id,
        )


__all__ = ["NumericalWorker", "choose_template", "template_unmodified"]
