"""The strategist: portfolio proposals from a model, or the template.

Used by :func:`opentorus.campaign.portfolio.generate_portfolio`, not scheduled as a
branch worker. With a real provider it asks for a JSON array of proposals (task class
``campaign_strategy``) through a one-turn bounded loop — so the call is routed,
recorded in the usage ledger under the campaign's tags, and counted by the engine's
usage collector — and hands the *raw items* back; the portfolio module validates
them and applies the mandatory rules. With the mock provider it makes no call at
all: the template portfolio is the deterministic answer, and a note says so.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from opentorus.campaign.models import (
    BranchKind,
    CampaignMode,
    CostTotals,
    RootRelation,
    RoutingHint,
    WorkBudget,
    WorkerContext,
    WorkerResult,
    WorkerRole,
)
from opentorus.campaign.workers.base import (
    WorkerRuntime,
    acquire_lease,
    bounded_loop,
    is_mock_provider,
)
from opentorus.errors import OpenTorusError

if TYPE_CHECKING:
    from pathlib import Path

    from opentorus.campaign.portfolio import PortfolioContext


KIND_ALIASES: dict[str, BranchKind] = {k.value: k for k in BranchKind} | {
    "special_case": BranchKind.special_case,
    "specialcase": BranchKind.special_case,
    "counter-example": BranchKind.counterexample,
    "formal": BranchKind.formalization,
    "numerics": BranchKind.numerical,
    "experiment": BranchKind.numerical,
    "lit": BranchKind.literature,
}
RELATION_ALIASES: dict[str, RootRelation] = {r.value: r for r in RootRelation} | {
    "special_case": RootRelation.special_case,
    "counterexample_route": RootRelation.counterexample_route,
    "counterexample": RootRelation.counterexample_route,
    "refutation": RootRelation.counterexample_route,
    "support": RootRelation.supporting,
    "supports": RootRelation.supporting,
    "equivalence": RootRelation.equivalent,
}


_WRAPPER_KEYS = ("proposals", "branches", "portfolio", "strategies", "items")
_TRAILING_COMMA = re.compile(r",(\s*[\]}])")
# Either a valid JSON escape (kept whole) or a lone backslash starting none of them
# ("\m" in "$\mathbb{E}$", "\d" in "\dots"). Matching valid escapes first consumes
# them atomically, so an already-doubled "\\sup" is not mangled into "\\\sup" —
# models mix both conventions inside one answer.
_ESCAPE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})|\\(.)', re.S)


def _repair_escapes(text: str) -> str:
    return _ESCAPE.sub(lambda m: m.group(0) if m.group(1) else "\\\\" + m.group(2), text)


def _loads_lenient(text: str) -> object | None:
    """``json.loads`` that also survives trailing commas and LaTeX backslashes.

    Five of five stress campaigns lost their model portfolio because a proposal
    contained LaTeX inside a JSON string (``$\\mathbb{E}\\vartheta(G)/\\sqrt{n}$``):
    ``\\m`` is not a JSON escape, so the whole answer was discarded. Doubling every
    invalid escape reconstructs the string the model meant; valid answers are
    untouched because the raw text is always tried first.
    """
    candidates = [text, _TRAILING_COMMA.sub(r"\1", text)]
    candidates += [_repair_escapes(c) for c in list(candidates)]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def parse_strategist_json(text: str) -> list[dict[str, object]]:
    """The proposal list in a model answer, tolerating the shapes models actually produce.

    Accepted: a bare JSON array (possibly wrapped in prose or code fences), an object
    wrapping the array under ``proposals``/``branches``/``portfolio``/``strategies``/
    ``items``, and trailing commas. A real run fell back to the template portfolio
    because gemma4 answered ``{"proposals": [...]}`` — a legitimate answer the strict
    array-only reader threw away.
    """
    if not text:
        return []
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if not starts:
        return []
    start = min(starts)
    closer = "]" if text[start] == "[" else "}"
    end = text.rfind(closer)
    if end <= start:
        return []
    data = _loads_lenient(text[start : end + 1])
    if isinstance(data, dict):
        for key in _WRAPPER_KEYS:
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            # An object holding exactly one list value is the wrapper too.
            lists = [v for v in data.values() if isinstance(v, list)]
            data = lists[0] if len(lists) == 1 else None
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def strategist_prompt(ctx: PortfolioContext) -> str:
    from opentorus.campaign.portfolio import PORTFOLIO_SLACK

    kinds = ", ".join(k.value for k in BranchKind)
    relations = ", ".join(r.value for r in RootRelation)
    problem = ctx.problem
    assumptions = "\n".join(f"- {a}" for a in problem.assumptions) or "- (none recorded)"
    coverage = ", ".join(ctx.coverage_insufficient) or "none"
    return (
        f"You are the strategist of a {CampaignMode(str(ctx.mode)).value} campaign on problem "
        f"{problem.problem_id}.\n\nStatement:\n{problem.statement}\n\n"
        f"Recorded assumptions:\n{assumptions}\n\n"
        f"Insufficient literature coverage categories: {coverage}\n\n"
        f"Propose {ctx.initial_branches + PORTFOLIO_SLACK} distinct lines of attack as a "
        'JSON array. Each element: {"title": str, "kind": one of [' + kinds + "], "
        '"objective": str, "strategy_summary": str, "root_relation": one of [' + relations + "], "
        '"assumption_context": [str], "why_distinct": str}. Include a proof route and a '
        "counterexample route; include a literature branch when coverage is insufficient. "
        "Answer with the JSON array only."
    )


def strategist_context(ctx: PortfolioContext) -> WorkerContext:
    """A worker context for the portfolio step (no branch, no work item)."""
    from opentorus.providers.pool import TaskClass

    return WorkerContext(
        campaign_id=ctx.campaign_id,
        branch_id=None,
        work_item_id=None,
        role=WorkerRole.strategist,
        task_class=TaskClass.campaign_strategy.value,
        mode=ctx.mode,
        root_problem=ctx.problem,
        budget=WorkBudget(max_steps=1),
        session_id=f"{ctx.campaign_id}:campaign:strategist",
        routing_hint=RoutingHint(required_capabilities=[]),
        insufficient_categories=tuple(ctx.coverage_insufficient),
    )


def _preserve_raw_answer(ot_dir: Path, campaign_id: str, answer: str) -> str | None:
    """Persist an unparseable strategist answer under the campaign dir; relpath or None.

    A 160-char excerpt in the event note is not enough to diagnose (or re-parse) a
    discarded portfolio; the full text is kept next to the campaign log.
    """
    if not answer.strip():
        return None
    try:
        from opentorus.campaign import paths

        _pid, cdir = paths.find_campaign(ot_dir, campaign_id)
        target = cdir / "strategist-answers"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"answer-{len(list(target.glob('answer-*.txt'))) + 1:03d}.txt"
        path.write_text(answer, encoding="utf-8")
        return str(path.relative_to(ot_dir))
    except Exception:  # noqa: BLE001 - preservation must never break the portfolio phase
        return None


def propose_with_model(
    runtime: WorkerRuntime, ctx: PortfolioContext
) -> tuple[list[dict[str, object]], list[str]]:
    """``(items, notes)``: the strategist's JSON items, or none with a note saying why.

    Never raises for a provider problem — an unusable strategist is a template
    fallback with a note, not a failed campaign.
    """
    from opentorus.tools.registry import ToolRegistry

    wctx = strategist_context(ctx)
    try:
        lease = acquire_lease(wctx, runtime)
    except OpenTorusError as exc:
        return [], [f"strategist: no eligible provider ({exc}); template portfolio used"]
    if is_mock_provider(lease.provider):
        return [], ["strategist: mock provider; template portfolio used"]
    try:
        loop = bounded_loop(wctx, runtime, lease=lease, registry=ToolRegistry())
        answer = loop.run(strategist_prompt(ctx))
    # The docstring's promise is "never raises for a provider problem", and only
    # OpenTorusError was caught — so every provider SDK exception escaped. A vLLM
    # endpoint answering 400 on the strategist's first call took six campaigns down
    # with it, before a single work item had run. KeyboardInterrupt and SystemExit
    # are not Exception subclasses, so a Ctrl-C still stops the campaign.
    except Exception as exc:  # noqa: BLE001 - deliberate: degrade, never abort
        detail = exc if isinstance(exc, OpenTorusError) else f"{type(exc).__name__}: {exc}"
        return [], [f"strategist: provider error ({detail}); template portfolio used"]
    items = parse_strategist_json(answer)
    if not items:
        excerpt = " ".join((answer or "").split())[:160]
        note = "strategist: answer was not a JSON array of proposals; template portfolio used" + (
            f" (answer began: {excerpt!r})" if excerpt else " (empty answer)"
        )
        kept = _preserve_raw_answer(runtime.ot_dir, ctx.campaign_id, answer or "")
        if kept:
            note += f"; full answer preserved at {kept}"
        return [], [note]
    return items, [
        f"strategist: {len(items)} proposal(s) from {lease.profile_name} "
        f"({lease.decision.decision_id})"
    ]


class StrategistWorker:
    """Registered for completeness: a strategist work item re-runs the proposal step
    and reports the items as notes (the engine's portfolio phase is the real caller)."""

    role = WorkerRole.strategist

    def run(self, ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult:
        from opentorus.campaign.portfolio import PortfolioContext

        pctx = PortfolioContext(
            campaign_id=ctx.campaign_id,
            mode=ctx.mode,
            problem=ctx.root_problem,
            coverage_insufficient=tuple(ctx.insufficient_categories),
        )
        items, notes = propose_with_model(rt, pctx)
        notes.append(f"{len(items)} strategist item(s)")
        return WorkerResult(status="completed", notes=notes, usage=CostTotals())


__all__ = [
    "KIND_ALIASES",
    "RELATION_ALIASES",
    "StrategistWorker",
    "parse_strategist_json",
    "propose_with_model",
    "strategist_context",
    "strategist_prompt",
]
