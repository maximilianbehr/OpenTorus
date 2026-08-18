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

The iteration body lives in :mod:`opentorus.agent.research_iteration`; this module
is the façade: state files, budgets, resumption, and — **opt-in only**
(``record_campaign=True`` / ``campaign.record_research`` / ``research --campaign``,
and only when a problem is attributed) — a mirror of the run into an exploration
campaign under that problem. A plain run writes exactly what it always wrote.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from opentorus.agent.research_iteration import (
    ensure_target_claim as _ensure_target_claim,  # noqa: F401 - re-exported private name
)
from opentorus.agent.research_iteration import (
    parse_search_result as _parse_search_result,  # noqa: F401 - re-exported private name
)
from opentorus.agent.research_iteration import (
    record_turn as _record_turn,  # noqa: F401 - re-exported private name
)
from opentorus.agent.research_iteration import (
    run_iteration as _run_iteration,
)
from opentorus.config import Config
from opentorus.providers.base import BaseProvider

if TYPE_CHECKING:
    from opentorus.campaign.research_bridge import ResearchCampaignRecorder
    from opentorus.providers.pool import ProviderPool

_logger = logging.getLogger("opentorus")

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
    return load_state_by_slug(ot_dir, _slugify(question))


def load_state_by_slug(ot_dir: Path, slug: str) -> ResearchState | None:
    """The persisted state of the investigation with this slug (the state file's stem)."""
    path = _state_path(ot_dir, slug)
    if path.is_file():
        return ResearchState.model_validate_json(path.read_text(encoding="utf-8"))
    return None


def list_states(ot_dir: Path) -> list[ResearchState]:
    """Every persisted investigation, by slug (the importer lists them for a human)."""
    directory = _state_dir(ot_dir)
    if not directory.is_dir():
        return []
    states: list[ResearchState] = []
    for path in sorted(directory.glob("*.json")):
        try:
            states.append(ResearchState.model_validate_json(path.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return states


def _save_state(ot_dir: Path, state: ResearchState) -> None:
    _state_dir(ot_dir).mkdir(parents=True, exist_ok=True)
    _state_path(ot_dir, state.slug).write_text(state.model_dump_json(indent=2), encoding="utf-8")


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


def _record_or_disable(action: Callable[[], None]) -> bool:
    """Run one recording step; a campaign-store error is logged and returns ``False`` so
    the caller disables further recording — the mirror is a courtesy and must never
    break the research run itself."""
    from opentorus.errors import OpenTorusError

    try:
        action()
    except OpenTorusError as exc:
        _logger.warning("campaign recording of the research run stopped: %s", exc)
        return False
    return True


def _campaign_recorder(
    ot_dir: Path, config: Config, record_campaign: bool | None
) -> ResearchCampaignRecorder | None:
    """The campaign mirror for this run, or ``None`` (the default): opt-in, and only
    when a problem is attributed — an unattributed run has no dossier to live under."""
    from opentorus.research.dossier.store import get_active_problem

    wanted = record_campaign if record_campaign is not None else config.campaign.record_research
    if not wanted:
        return None
    problem_id = get_active_problem(ot_dir)
    if problem_id is None:
        return None
    from opentorus.campaign.research_bridge import ResearchCampaignRecorder

    return ResearchCampaignRecorder(ot_dir, config, problem_id=problem_id)


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
    record_campaign: bool | None = None,
) -> ResearchOutcome:
    """Start or continue an autonomous investigation of ``question``.

    Runs iterations until the global iteration cap or a budget is reached, then
    stops cleanly and reports state. Re-running with the same question resumes
    from the next unfinished iteration.

    ``record_campaign`` (``None`` → ``config.campaign.record_research``): when true
    *and* a problem is attributed (the active dossier), the run is also mirrored into
    an exploration campaign under that problem — created lazily on the first
    iteration, one numerical branch, one work item per iteration with the EXP/EVIDENCE/
    CLAIM ids as artifact references — and completed when the run stops. The research
    state file, progress note, journal and checkpoints are written exactly as before
    either way.
    """
    from opentorus.agent.context import reset_retrieval_breaker
    from opentorus.research.checkpoints import create_checkpoint
    from opentorus.usage import summarize_usage

    # A breaker tripped in an earlier run must not disable retrieval for this one.
    reset_retrieval_breaker()
    state = load_state(ot_dir, question) or ResearchState(
        question=question, slug=_slugify(question)
    )
    state.status = "running"
    state.stopped_reason = None
    recorder = _campaign_recorder(ot_dir, config, record_campaign)

    results: list[IterationResult] = []
    stopped_reason = "iteration cap reached"

    from opentorus.governance import breached_budgets

    # One pool for the whole run (routing enabled only): provider instances are
    # cached per profile and the routing-decision counter is seeded from the ledger
    # once, instead of re-reading the ledger and rebuilding providers every turn.
    pool: ProviderPool | None = None
    if config.governance.routing.enabled:
        from opentorus.providers.pool import build_pool

        pool = build_pool(config, ot_dir)

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
            root, ot_dir, provider, config, state, iteration, max_steps_per_iteration, pool=pool
        )
        results.append(result)
        state.completed_iterations = iteration
        state.progress_path = _write_progress_note(ot_dir, state)
        _save_state(ot_dir, state)
        create_checkpoint(root, ot_dir, f"research {state.slug} iter {iteration}")
        if recorder is not None and not _record_or_disable(
            partial(recorder.record_iteration, state, result)
        ):
            recorder = None

    state.status = "stopped" if stopped_reason != "iteration cap reached" else "completed"
    state.stopped_reason = stopped_reason
    _save_state(ot_dir, state)
    if recorder is not None:
        _record_or_disable(partial(recorder.finish, f"research run stopped: {stopped_reason}"))

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


__all__ = [
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MAX_STEPS_PER_ITERATION",
    "IterationResult",
    "ResearchOutcome",
    "ResearchState",
    "list_states",
    "load_state",
    "load_state_by_slug",
    "run_research",
]
