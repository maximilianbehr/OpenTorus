"""One iteration of the autonomous research loop, and the narration turn it ends with.

Moved verbatim out of :mod:`opentorus.agent.research_loop` so the loop module is the
thin façade (state, budgets, resumption, the optional campaign recording) and the
iteration body — literature glance, target claim, state-aware experiment, evidence,
adversarial review, narration, journal entry — is one importable unit. Nothing about
the behaviour changed: ``run_research`` calls :func:`run_iteration` exactly where it
called ``_run_iteration`` before, and the private names stay importable from
``research_loop`` for callers that used them.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.providers.base import BaseProvider
from opentorus.research.math_experiments import CounterexampleResult

if TYPE_CHECKING:
    from opentorus.agent.research_loop import IterationResult, ResearchState
    from opentorus.providers.pool import ProviderPool


def record_turn(
    ot_dir: Path,
    config: Config,
    provider: BaseProvider,
    prompt: str,
    *,
    task_class: str = "narration",
    pool: ProviderPool | None = None,
) -> str:
    """One provider turn for narration; routes the model and records usage (M31/M75).

    With routing enabled the provider is *acquired* from the pool for the task class
    (so a ``task_routes``/``task_models`` entry really changes who answers) and the
    decision is recorded in ``usage/routing.jsonl``. With routing disabled the caller's
    provider is used unchanged. Either way the ledger records the provider and model
    that actually answered — never a chosen-but-unused route. When no routed profile
    is eligible the pool's ``NoEligibleProviderError`` propagates (after being
    recorded): the caller's provider is itself the default candidate, so silently
    using it would bypass whatever made it ineligible (e.g. a per-provider budget).

    ``pool`` is the run's shared pool (built once by ``run_research``) so provider
    instances and the decision counter are reused across turns; ``None`` builds one
    for this turn, which keeps older callers working.
    """
    from opentorus.agent.compaction import estimate_tokens, total_tokens
    from opentorus.errors import OpenTorusError
    from opentorus.usage import UsageRecord, cost_known, estimate_cost, record_usage

    messages = [SessionMessage(role="user", content=prompt)]
    active = provider
    lease = None
    if config.governance.routing.enabled:
        if pool is None:
            from opentorus.providers.pool import build_pool

            pool = build_pool(config, ot_dir)
        lease = pool.acquire(task_class)
        active = lease.provider
    model = getattr(active, "model_name", None) or config.model.name
    base_url = lease.profile.base_url if lease is not None else config.model.base_url
    started = time.monotonic()
    response = active.respond(messages)
    elapsed = time.monotonic() - started
    actual_model = response.model or model
    if lease is not None and pool is not None and response.model:
        pool.note_actual_model(lease.decision.decision_id, response.model)

    provider_name = getattr(active, "name", "unknown")
    prompt_tokens = total_tokens(messages)
    completion_tokens = estimate_tokens(response.content) if response.content else 0
    try:
        record_usage(
            ot_dir,
            UsageRecord(
                session_id=None,
                provider=provider_name,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=round(elapsed * 1000),
                cost_usd=estimate_cost(
                    provider_name, model, prompt_tokens, completion_tokens, base_url
                ),
                cost_known=cost_known(provider_name, model, base_url),
                task_class=task_class,
                routing_decision_id=lease.decision.decision_id if lease else None,
                requested_profile=lease.decision.requested_profile if lease else None,
                selected_profile=lease.profile_name if lease else None,
                configured_model=model,
                actual_model=actual_model,
                fallback_reason=lease.decision.fallback_reason if lease else None,
            ),
        )
    except OpenTorusError:
        pass
    return response.content


def parse_search_result(stdout: str) -> CounterexampleResult | None:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("kind") != "counterexample_search":
            continue
        rng = data.get("searched_range") or [0, 0]
        ce = data.get("counterexample")
        return CounterexampleResult(
            start=int(rng[0]),
            stop=int(rng[1]),
            step=int(data.get("step", 1)),
            checked=int(data.get("checked", 0)),
            found=ce is not None,
            counterexample=ce,
        )
    return None


def ensure_target_claim(ot_dir: Path, state: ResearchState) -> str:
    """Pick the claim to work on: an existing gap, else a new conjecture."""
    from opentorus.research.claims import get_claim, new_claim
    from opentorus.research.dossier.store import get_active_problem
    from opentorus.research.knowledge import find_gaps

    if state.target_claim_id and get_claim(ot_dir, state.target_claim_id):
        return state.target_claim_id
    gaps = find_gaps(ot_dir)
    if gaps:
        state.target_claim_id = gaps[0].claim_id
        return state.target_claim_id
    claim = new_claim(ot_dir, state.question, problem_id=get_active_problem(ot_dir))
    from opentorus.research.claims import update_claim

    update_claim(ot_dir, claim.id, status="conjecture")
    state.target_claim_id = claim.id
    return claim.id


def run_iteration(
    root: Path,
    ot_dir: Path,
    provider: BaseProvider,
    config: Config,
    state: ResearchState,
    iteration: int,
    max_steps: int,
    *,
    pool: ProviderPool | None = None,
) -> IterationResult:
    from opentorus.agent.research_loop import IterationResult
    from opentorus.research.claims import get_claim, update_claim
    from opentorus.research.experiments import new_experiment, run_experiment
    from opentorus.research.journal import JournalEntry, add_entry
    from opentorus.research.knowledge import propose_hypotheses
    from opentorus.research.math_experiments import record_search_evidence
    from opentorus.research.papers import list_papers

    actions: list[str] = []
    goal = f"Iteration {iteration}: advance '{state.question}'."

    # (1) Literature: review the local corpus (offline, best-effort).
    papers = list_papers(ot_dir)
    actions.append(f"Reviewed local corpus: {len(papers)} paper(s).")

    # (2) Hypothesis: surface gaps and pick/define the claim under study.
    claim_id = ensure_target_claim(ot_dir, state)
    hypotheses = propose_hypotheses(ot_dir)
    hypothesis_id = hypotheses[0].id if hypotheses else None
    actions.append(f"Proposed {len(hypotheses)} hypothesis/-es; studying {claim_id}.")

    # (3) Experiment: state-aware so iterations are not redundant. If a prior
    # iteration already produced a counterexample (contradicting evidence on the
    # claim), stop re-searching and switch to rigorously confirming it via validated
    # numerics; otherwise keep searching for one.
    from opentorus.research.dossier.store import get_active_problem
    from opentorus.research.evidence import list_evidence

    prior_counterexample = any(
        e.direction in ("contradicts", "mixed") for e in list_evidence(ot_dir, claim_id)
    )
    template = "validated_numerics" if prior_counterexample else "counterexample_search"
    actions.append(
        "Counterexample already found — switching to validated-numerics confirmation."
        if prior_counterexample
        else "Searching for a counterexample."
    )
    exp = new_experiment(
        ot_dir,
        f"{state.slug} iter {iteration}",
        template=template,
        problem_id=get_active_problem(ot_dir),
    )
    exp, _code = run_experiment(ot_dir, exp.id, timeout=min(120, 20 * max_steps))
    stdout = (ot_dir / exp.path / "results" / "stdout.txt").read_text(encoding="utf-8")
    result = parse_search_result(stdout)
    actions.append(f"Ran {exp.id} ({exp.status}).")

    # (4) Evidence + claim status under proof-status rules (M52).
    evidence_id: str | None = None
    claim_status: str | None = None
    if result is not None:
        evidence, _advisory = record_search_evidence(ot_dir, claim_id, result)
        evidence_id = evidence.id
        claim = get_claim(ot_dir, claim_id)
        # Only advance toward bounded numerical evidence — never to a verified
        # class. A clean bounded search supports; a counterexample refutes.
        if claim is not None:
            if result.found:
                actions.append("Counterexample found — strong contradicting evidence.")
            elif claim.status in {"idea", "observation", "evidence", "hypothesis", "conjecture"}:
                update_claim(ot_dir, claim_id, status="numerical_evidence")
            claim = get_claim(ot_dir, claim_id)
            claim_status = claim.status if claim else None

    # (4b) Adversarial review: an independent critic challenges the claim (M58-60).
    from opentorus.agent.review import open_blocking_findings, review_target

    review = review_target(ot_dir, claim_id)
    blocking = len(open_blocking_findings(ot_dir, claim_id))
    actions.append(f"Critic review {review.id}: verdict {review.verdict} ({blocking} blocking).")

    # (5) Narration turn (records usage for budgeting) + next step.
    next_step = record_turn(
        ot_dir,
        config,
        provider,
        f"Investigation: {state.question}\nLatest: {actions[-1]}\n"
        "State the single most useful next step (one sentence).",
        pool=pool,
    ).strip()

    add_entry(
        ot_dir,
        JournalEntry(
            id="",
            investigation=state.slug,
            iteration=iteration,
            goal=goal,
            actions=actions,
            evidence_ids=[evidence_id] if evidence_id else [],
            claim_id=claim_id,
            claim_status=claim_status,
            next_step=next_step or "Continue gathering bounded evidence.",
        ),
    )

    return IterationResult(
        iteration=iteration,
        goal=goal,
        hypothesis_id=hypothesis_id,
        experiment_id=exp.id,
        evidence_id=evidence_id,
        claim_id=claim_id,
        claim_status=claim_status,
    )


__all__ = ["ensure_target_claim", "parse_search_result", "record_turn", "run_iteration"]
