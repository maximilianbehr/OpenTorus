"""Autonomous research orchestrator (Milestone 53).

Drives the full cycle — question → literature → hypothesis → experiment/proof →
evidence → claim/graph update → progress report — over many iterations, within
explicit budgets and with everything recorded as evidence. It *composes* existing
parts (experiments M50, proof-status M52, checkpoints M15, usage ledger M31,
reports M48, hypotheses M49, journal M54) rather than inventing new control flow.

Invariants: bounded (iteration + step caps, token/cost budget), resumable (state
is persisted; re-running continues from the next unfinished step), and honest
(nothing is auto-promoted past ``numerical_evidence`` — verified-class statuses
still require a proof artifact and confirmation).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.providers.base import BaseProvider
from opentorus.research.math_experiments import CounterexampleResult

DEFAULT_MAX_ITERATIONS = 5
DEFAULT_MAX_STEPS_PER_ITERATION = 6


def _slugify(question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.strip().lower()).strip("-")
    return (slug[:60] or "investigation").rstrip("-")


class ResearchState(BaseModel):
    """Persisted state of an investigation, enabling faithful resumption."""

    question: str
    slug: str
    target_claim_id: str | None = None
    progress_path: str | None = None
    completed_iterations: int = 0
    status: str = "running"
    stopped_reason: str | None = None


class IterationResult(BaseModel):
    iteration: int
    goal: str
    hypothesis_id: str | None = None
    experiment_id: str | None = None
    evidence_id: str | None = None
    claim_id: str | None = None
    claim_status: str | None = None


class ResearchOutcome(BaseModel):
    question: str
    slug: str
    iterations_run: int = 0
    total_iterations: int = 0
    stopped_reason: str = ""
    progress_path: str | None = None
    cost_usd: float = 0.0
    total_tokens: int = 0
    results: list[IterationResult] = Field(default_factory=list)


def _state_dir(ot_dir: Path) -> Path:
    return ot_dir / "research"


def _state_path(ot_dir: Path, slug: str) -> Path:
    return _state_dir(ot_dir) / f"{slug}.json"


def load_state(ot_dir: Path, question: str) -> ResearchState | None:
    path = _state_path(ot_dir, _slugify(question))
    if path.is_file():
        return ResearchState.model_validate_json(path.read_text(encoding="utf-8"))
    return None


def _save_state(ot_dir: Path, state: ResearchState) -> None:
    _state_dir(ot_dir).mkdir(parents=True, exist_ok=True)
    _state_path(ot_dir, state.slug).write_text(state.model_dump_json(indent=2), encoding="utf-8")


def _record_turn(
    ot_dir: Path,
    config: Config,
    provider: BaseProvider,
    prompt: str,
    *,
    task_class: str = "narration",
) -> str:
    """One provider turn for narration; routes the model and records usage (M31/M75)."""
    from opentorus.agent.compaction import estimate_tokens, total_tokens
    from opentorus.errors import OpenTorusError
    from opentorus.governance import route_model
    from opentorus.usage import UsageRecord, estimate_cost, record_usage

    messages = [SessionMessage(role="user", content=prompt)]
    # Policy model routing (M75): pick a model for this task class, recorded below.
    decision = route_model(config, task_class)
    model = decision.model
    started = time.monotonic()
    response = provider.respond(messages)
    elapsed = time.monotonic() - started

    provider_name = getattr(provider, "name", "unknown")
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
                cost_usd=estimate_cost(provider_name, model, prompt_tokens, completion_tokens),
                task_class=decision.task_class,
            ),
        )
    except OpenTorusError:
        pass
    return response.content


def _parse_search_result(stdout: str) -> CounterexampleResult | None:
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


def _ensure_target_claim(ot_dir: Path, state: ResearchState) -> str:
    """Pick the claim to work on: an existing gap, else a new conjecture."""
    from opentorus.research.claims import get_claim, new_claim
    from opentorus.research.knowledge import find_gaps

    if state.target_claim_id and get_claim(ot_dir, state.target_claim_id):
        return state.target_claim_id
    gaps = find_gaps(ot_dir)
    if gaps:
        state.target_claim_id = gaps[0].claim_id
        return state.target_claim_id
    claim = new_claim(ot_dir, state.question)
    from opentorus.research.claims import update_claim

    update_claim(ot_dir, claim.id, status="conjecture")
    state.target_claim_id = claim.id
    return claim.id


def _run_iteration(
    root: Path,
    ot_dir: Path,
    provider: BaseProvider,
    config: Config,
    state: ResearchState,
    iteration: int,
    max_steps: int,
) -> IterationResult:
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
    claim_id = _ensure_target_claim(ot_dir, state)
    hypotheses = propose_hypotheses(ot_dir)
    hypothesis_id = hypotheses[0].id if hypotheses else None
    actions.append(f"Proposed {len(hypotheses)} hypothesis/-es; studying {claim_id}.")

    # (3) Experiment: run a bounded counterexample search (reproducible, M50).
    exp = new_experiment(ot_dir, f"{state.slug} iter {iteration}", template="counterexample_search")
    exp, _code = run_experiment(ot_dir, exp.id, timeout=min(120, 20 * max_steps))
    stdout = (ot_dir / exp.path / "results" / "stdout.txt").read_text(encoding="utf-8")
    result = _parse_search_result(stdout)
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
    next_step = _record_turn(
        ot_dir,
        config,
        provider,
        f"Investigation: {state.question}\nLatest: {actions[-1]}\n"
        "State the single most useful next step (one sentence).",
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


def _write_progress_note(ot_dir: Path, state: ResearchState) -> str:
    """Refresh the investigation progress markdown under ``.opentorus/research/``."""
    from opentorus.research.claims import get_claim
    from opentorus.research.journal import list_entries

    entries = list_entries(ot_dir, state.slug)
    lines = [
        "> Autonomous research progress: **evidence**, not final truth. "
        "Bounded numerical evidence is not a proof.\n",
        f"## Question\n\n- {state.question}\n",
    ]
    claim = get_claim(ot_dir, state.target_claim_id) if state.target_claim_id else None
    if claim is not None:
        lines.append(f"## Claim under study\n\n- {claim.id} [{claim.status}]: {claim.statement}\n")
    lines.append("## Iterations\n")
    for e in entries:
        lines.append(f"### Iteration {e.iteration} ({e.id})")
        lines.extend(f"- {a}" for a in e.actions)
        if e.evidence_ids:
            lines.append(f"- Evidence: {', '.join(e.evidence_ids)}")
        lines.append(f"- Next step: {e.next_step}")
        lines.append("")
    body = "\n".join(lines)

    rel = f"research/{state.slug}/progress.md"
    path = ot_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Research progress — {state.question}\n\n{body.rstrip()}\n", encoding="utf-8"
    )
    return rel


def run_research(
    root: Path,
    ot_dir: Path,
    provider: BaseProvider,
    config: Config,
    question: str,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_steps_per_iteration: int = DEFAULT_MAX_STEPS_PER_ITERATION,
    cost_budget_usd: float | None = None,
    token_budget: int | None = None,
) -> ResearchOutcome:
    """Start or continue an autonomous investigation of ``question``.

    Runs iterations until the global iteration cap or a budget is reached, then
    stops cleanly and reports state. Re-running with the same question resumes
    from the next unfinished iteration.
    """
    from opentorus.research.checkpoints import create_checkpoint
    from opentorus.usage import summarize_usage

    state = load_state(ot_dir, question) or ResearchState(
        question=question, slug=_slugify(question)
    )
    state.status = "running"
    state.stopped_reason = None

    results: list[IterationResult] = []
    stopped_reason = "iteration cap reached"

    from opentorus.governance import breached_budgets

    while state.completed_iterations < max_iterations:
        summary = summarize_usage(ot_dir)
        if cost_budget_usd is not None and summary.cost_usd >= cost_budget_usd:
            stopped_reason = "cost budget reached"
            break
        if token_budget is not None and summary.total_tokens >= token_budget:
            stopped_reason = "token budget reached"
            break
        # Governance budgets (M75) stop the loop cleanly when breached.
        governance_breaches = breached_budgets(ot_dir, config)
        if governance_breaches:
            stopped_reason = f"governance budget reached: {governance_breaches[0].message}"
            break

        iteration = state.completed_iterations + 1
        result = _run_iteration(
            root, ot_dir, provider, config, state, iteration, max_steps_per_iteration
        )
        results.append(result)
        state.completed_iterations = iteration
        state.progress_path = _write_progress_note(ot_dir, state)
        _save_state(ot_dir, state)
        create_checkpoint(root, ot_dir, f"research {state.slug} iter {iteration}")

    state.status = "stopped" if stopped_reason != "iteration cap reached" else "completed"
    state.stopped_reason = stopped_reason
    _save_state(ot_dir, state)

    final = summarize_usage(ot_dir)
    return ResearchOutcome(
        question=question,
        slug=state.slug,
        iterations_run=len(results),
        total_iterations=state.completed_iterations,
        stopped_reason=stopped_reason,
        progress_path=state.progress_path,
        cost_usd=final.cost_usd,
        total_tokens=final.total_tokens,
        results=results,
    )
