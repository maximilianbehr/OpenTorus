"""Portfolio construction: which branches a campaign opens, and which it turns down.

The pipeline is deterministic end to end and every decision leaves a record:

1. **Proposals** come from :func:`template_portfolio` — the mode's fixed recipe
   (``phases.ModeProfile.portfolio_recipe``) rendered with the dossier's
   ``dossier.strategies.STRATEGY_TEMPLATES`` text — or from the LLM strategist
   (:func:`generate_portfolio` with a real provider; JSON in, validated leniently,
   template fallback recorded in the notes when the answer is unusable). Under the
   mock provider the template is used directly, which is what makes two fresh
   workspaces produce identical logs.
2. :func:`dedup_proposals` — token-set Jaccard ≥ 0.8 on the normalised objective
   *and* the same ``(kind, root_relation)`` → the later proposal is rejected
   ``REPEATED_STRATEGY`` with ``duplicate_of``; survivors get a ``distinctness_note``.
3. :func:`cap_proposals` — the first ``initial_branches`` survivors are kept, the rest
   are rejected ``PORTFOLIO_CAP`` (kept in the log, never discarded). Mandatory
   branches survive the cap: prove-or-refute always keeps a proof *and* a
   counterexample route, and a literature branch is forced while critical coverage is
   insufficient.
4. :func:`activate_initial` — the top ``max_active_branches`` by priority (tie-break
   ``branch_id``) are activated; the same mandatory rules apply (a mandatory branch is
   swapped in for the lowest-priority slot). The remaining accepted branches stay
   ``proposed`` (queued) and are activated in REALLOCATE when a slot frees up.

Priority is ``1.0 - 0.1 * index`` in proposal order (clamped at 0), so the recipe's
order *is* the initial preference and the scheduler's factors take over from there.
Branch ids are minted from the snapshot's ``BRANCH`` counter by the caller (the
engine); this module never reads a clock or the disk.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from opentorus.agent.control.models import ReasonCode
from opentorus.campaign import ids
from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignSnapshot,
    NormalizedProblem,
    RootRelation,
    WorkerRole,
)

if TYPE_CHECKING:
    from opentorus.campaign.workers.base import WorkerRuntime

JACCARD_DUPLICATE_THRESHOLD = 0.8
# The template proposes a few more strategies than the campaign keeps, so dedup and
# the mandatory rules have alternatives; the surplus is rejected PORTFOLIO_CAP.
PORTFOLIO_SLACK = 3
_TOKEN = re.compile(r"[a-z0-9]+")

# Which worker owns a branch of each kind.
KIND_TO_ROLE: dict[BranchKind, WorkerRole] = {
    BranchKind.proof: WorkerRole.prover,
    BranchKind.counterexample: WorkerRole.falsifier,
    BranchKind.literature: WorkerRole.librarian,
    BranchKind.special_case: WorkerRole.prover,
    BranchKind.symbolic: WorkerRole.symbolic_experimenter,
    BranchKind.numerical: WorkerRole.numerical_experimenter,
    BranchKind.formalization: WorkerRole.formalizer,
    BranchKind.obstruction: WorkerRole.prover,
    BranchKind.synthesis: WorkerRole.synthesizer,
}

# Human titles for the recipe strategies (the objective text comes from the dossier's
# strategy templates so the approach card and the branch say the same thing).
STRATEGY_TITLES: dict[str, str] = {
    "proof_sketch": "Proof route",
    "counterexample_search": "Counterexample search",
    "literature_map": "Literature map",
    "formalization_attempt": "Formalization attempt",
    "special_cases": "Special cases",
    "obstruction_search": "Obstruction search",
    "symbolic_simplification": "Symbolic simplification",
    "numerical_experiment": "Numerical experiments",
}

# One short, distinct hint per coverage category, so per-category survey branches
# do not collapse into each other under the Jaccard dedup.
COVERAGE_HINTS: dict[str, str] = {
    "original_problem_source": "locate the paper or note that first posed the problem",
    "definitions_notation": "pin the definitions and notation the statement relies on",
    "strongest_known_positive_results": "collect the strongest theorems proved toward it",
    "known_negative_results": "collect impossibility and lower-bound results against it",
    "known_counterexamples": "collect published counterexamples to nearby statements",
    "special_cases": "collect the settled special cases and restricted regimes",
    "equivalent_formulations": "collect equivalent reformulations and reductions",
    "standard_tools_lemmas": "collect the standard lemmas and tools attacks rely on",
    "recent_developments": "collect the most recent developments and preprints",
    "survey_synthesis_sources": "collect surveys and synthesis sources",
    "unresolved_gaps": "collect explicitly stated open gaps and obstacles",
}


def normalize_objective(text: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(text.lower()))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def initial_priority(index: int) -> float:
    """``1.0 - 0.1 * index`` (clamped at 0): proposal order is the initial preference."""
    return round(max(0.0, 1.0 - 0.1 * index), 3)


# --------------------------------------------------------------------------------------
# proposals
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioContext:
    """What the portfolio step knows: the mode, the normalized problem, coverage."""

    campaign_id: str
    mode: CampaignMode
    problem: NormalizedProblem
    coverage_insufficient: tuple[str, ...] = ()
    critical_categories: tuple[str, ...] = ()
    initial_branches: int = 4
    max_active_branches: int = 3
    branch_counter: int = 0
    existing_branches: tuple[BranchRecord, ...] = ()


@dataclass
class PortfolioProposal:
    """The pipeline's output: everything proposed, sorted into what happens to it."""

    accepted: list[BranchRecord] = field(default_factory=list)
    rejected: list[BranchRecord] = field(default_factory=list)
    activated: list[BranchRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    source: str = "template"

    @property
    def proposals(self) -> list[BranchRecord]:
        """Every proposal in id order (accepted and rejected)."""
        return sorted([*self.accepted, *self.rejected], key=lambda b: b.branch_id)


def _template_text(strategy_key: str) -> tuple[str, str]:
    """``(objective, strategy_summary)`` from the dossier's strategy templates."""
    from opentorus.research.dossier.strategies import STRATEGY_TEMPLATES, StrategyTemplate

    templates = cast("dict[str, StrategyTemplate]", STRATEGY_TEMPLATES)
    template = templates.get(strategy_key)
    if template is None:
        return strategy_key.replace("_", " "), ""
    return template.objective, template.method


def _make_branch(
    *,
    campaign_id: str,
    branch_id: str,
    title: str,
    kind: BranchKind,
    objective: str,
    strategy_summary: str,
    root_relation: RootRelation,
    assumption_context: Sequence[str],
    index: int,
    strategy_key: str | None,
    parent_branch_id: str | None = None,
    distinctness_note: str = "",
) -> BranchRecord:
    return BranchRecord(
        branch_id=branch_id,
        campaign_id=campaign_id,
        title=title,
        kind=kind,
        objective=objective,
        strategy_summary=strategy_summary,
        root_relation=root_relation,
        assumption_context=list(assumption_context),
        parent_branch_id=parent_branch_id,
        status=BranchStatus.proposed,
        priority=initial_priority(index),
        estimated_cost=1.0,
        assigned_worker_role=KIND_TO_ROLE[kind],
        strategy_key=strategy_key,
        distinctness_note=distinctness_note,
    )


def template_portfolio(
    mode: CampaignMode | str,
    n: int,
    *,
    problem: NormalizedProblem,
    coverage: Sequence[str] = (),
    campaign_id: str = "",
    critical: Sequence[str] = (),
    start_index: int = 1,
) -> list[BranchRecord]:
    """The mode's recipe as branch proposals, in the fixed documented order.

    ``n`` caps how many proposals come back (the caller passes
    ``initial_branches + PORTFOLIO_SLACK`` so the cap step has a real surplus to
    reject and record). Ids are ``BRANCH-{start_index}`` onward — the caller passes
    the snapshot counter + 1 so a replay mints the same ids. ``coverage`` lists the
    insufficient critical categories (mentioned in the literature objective);
    ``critical`` lists all critical categories (survey expands one literature branch
    per category, then one synthesis branch).
    """
    from opentorus.campaign.phases import mode_profile

    resolved = CampaignMode(str(mode))
    profile = mode_profile(resolved)
    pid = problem.problem_id
    assumptions = list(problem.assumptions)
    out: list[BranchRecord] = []
    proof_branch_id: str | None = None
    insufficient = ", ".join(coverage) if coverage else "all critical categories"

    if resolved is CampaignMode.survey:
        categories = list(critical) or list(coverage)
        lit_objective, lit_summary = _template_text("literature_map")
        for category in categories:
            if len(out) >= max(0, n - 1):
                break
            hint = COVERAGE_HINTS.get(category, category.replace("_", " "))
            out.append(
                _make_branch(
                    campaign_id=campaign_id,
                    branch_id=ids.branch_id(start_index + len(out)),
                    title=f"Literature: {category.replace('_', ' ')}",
                    kind=BranchKind.literature,
                    objective=f"Cover the '{category}' literature category for {pid}: {hint}.",
                    strategy_summary=lit_summary or lit_objective,
                    root_relation=RootRelation.supporting,
                    assumption_context=assumptions,
                    index=len(out),
                    strategy_key="literature_map",
                )
            )
        if len(out) < n:
            out.append(
                _make_branch(
                    campaign_id=campaign_id,
                    branch_id=ids.branch_id(start_index + len(out)),
                    title="Survey synthesis",
                    kind=BranchKind.synthesis,
                    objective=(
                        f"Synthesize the mapped literature for {pid} into the dossier report "
                        "and progress notes; state what is known, cited, and open."
                    ),
                    strategy_summary=(
                        "Rebuild the report from local artifacts only; every claim of "
                        "knowledge cites a local paper or theorem reference."
                    ),
                    root_relation=RootRelation.supporting,
                    assumption_context=assumptions,
                    index=len(out),
                    strategy_key=None,
                )
            )
        return out

    for strategy_key, kind, relation in profile.portfolio_recipe:
        if len(out) >= n:
            break
        objective, summary = _template_text(strategy_key)
        if kind is BranchKind.literature:
            objective = f"Map the literature for {pid} ({insufficient}): {objective}"
        elif kind is BranchKind.special_case:
            objective = f"Special cases of {pid}: {objective}"
        else:
            objective = f"{objective} ({pid})"
        branch_id = ids.branch_id(start_index + len(out))
        parent = proof_branch_id if kind is BranchKind.special_case else None
        out.append(
            _make_branch(
                campaign_id=campaign_id,
                branch_id=branch_id,
                title=STRATEGY_TITLES.get(strategy_key, strategy_key.replace("_", " ")),
                kind=kind,
                objective=objective,
                strategy_summary=summary,
                root_relation=relation,
                assumption_context=assumptions,
                index=len(out),
                strategy_key=strategy_key,
                parent_branch_id=parent,
            )
        )
        if kind is BranchKind.proof and proof_branch_id is None:
            proof_branch_id = branch_id
    return out


# --------------------------------------------------------------------------------------
# dedup / cap / activation
# --------------------------------------------------------------------------------------


@dataclass
class DedupResult:
    accepted: list[BranchRecord] = field(default_factory=list)
    rejected: list[BranchRecord] = field(default_factory=list)  # status=rejected, duplicate_of set


def dedup_proposals(
    proposals: list[BranchRecord], *, threshold: float = JACCARD_DUPLICATE_THRESHOLD
) -> DedupResult:
    """First proposal wins; a later one with the same (kind, root_relation) and a
    Jaccard overlap ≥ ``threshold`` on its normalised objective is rejected as
    ``REPEATED_STRATEGY`` (kept, with ``duplicate_of`` naming the survivor). Survivors
    that were compared against something get a ``distinctness_note`` naming their
    closest accepted neighbour, so "why is this a separate branch" is answerable."""
    result = DedupResult()
    for proposal in proposals:
        tokens = normalize_objective(proposal.objective)
        dup: BranchRecord | None = None
        closest: tuple[float, str] | None = None
        for kept in result.accepted:
            overlap = jaccard(tokens, normalize_objective(kept.objective))
            if kept.kind is not proposal.kind or kept.root_relation is not proposal.root_relation:
                if closest is None or overlap > closest[0]:
                    closest = (overlap, kept.branch_id)
                continue
            if overlap >= threshold:
                dup = kept
                break
            if closest is None or overlap > closest[0]:
                closest = (overlap, kept.branch_id)
        if dup is None:
            note = proposal.distinctness_note
            if not note and closest is not None:
                note = (
                    f"distinct from {closest[1]} (Jaccard {closest[0]:.2f} < {threshold}, "
                    "or a different kind/root relation)"
                )
            elif not note:
                note = "first proposal of its kind"
            result.accepted.append(proposal.model_copy(update={"distinctness_note": note}))
        else:
            result.rejected.append(
                proposal.model_copy(
                    update={
                        "status": BranchStatus.rejected,
                        "rejection_reason": ReasonCode.REPEATED_STRATEGY.value,
                        "duplicate_of": dup.branch_id,
                        "distinctness_note": (
                            f"objective overlaps {dup.branch_id} (Jaccard >= {threshold})"
                        ),
                    }
                )
            )
    return result


def mandatory_branches(
    accepted: Sequence[BranchRecord],
    *,
    mode: CampaignMode | str | None,
    coverage_insufficient: Sequence[str] = (),
) -> list[BranchRecord]:
    """The branches that must survive the cap and be activated, in proposal order:
    the first proof and the first counterexample route in prove-or-refute; the first
    literature branch while any critical coverage category is insufficient."""
    wanted: list[BranchRecord] = []
    resolved = CampaignMode(str(mode)) if mode is not None else None
    if resolved is CampaignMode.prove_or_refute:
        for kind in (BranchKind.proof, BranchKind.counterexample):
            first = next((b for b in accepted if b.kind is kind), None)
            if first is not None and first not in wanted:
                wanted.append(first)
    if coverage_insufficient:
        first_lit = next((b for b in accepted if b.kind is BranchKind.literature), None)
        if first_lit is not None and first_lit not in wanted:
            wanted.append(first_lit)
    return sorted(wanted, key=lambda b: b.branch_id)


def cap_proposals(
    accepted: Sequence[BranchRecord],
    *,
    initial_branches: int,
    mode: CampaignMode | str | None = None,
    coverage_insufficient: Sequence[str] = (),
) -> DedupResult:
    """Keep the first ``initial_branches`` (plus the mandatory ones); reject the rest
    ``PORTFOLIO_CAP``. When the mandatory set is larger than the cap, all of it is
    kept anyway (a prove-or-refute campaign without both routes is not one)."""
    must = mandatory_branches(accepted, mode=mode, coverage_insufficient=coverage_insufficient)
    limit = max(int(initial_branches), len(must))
    keep_ids: list[str] = [b.branch_id for b in must]
    for branch in accepted:
        if len(keep_ids) >= limit:
            break
        if branch.branch_id not in keep_ids:
            keep_ids.append(branch.branch_id)
    result = DedupResult()
    for branch in accepted:
        if branch.branch_id in keep_ids:
            result.accepted.append(branch)
        else:
            result.rejected.append(
                branch.model_copy(
                    update={
                        "status": BranchStatus.rejected,
                        "rejection_reason": ReasonCode.PORTFOLIO_CAP.value,
                        "distinctness_note": (
                            f"distinct strategy, beyond the initial cap of {initial_branches}"
                        ),
                    }
                )
            )
    return result


def activate_initial(
    accepted: list[BranchRecord],
    *,
    max_active: int,
    mode: CampaignMode | str | None = None,
    coverage_insufficient: Sequence[str] = (),
) -> list[BranchRecord]:
    """The branches to activate first: top ``max_active`` by priority, ties by branch id.

    Mandatory branches (:func:`mandatory_branches`) are swapped in for the lowest
    slots when the cap would exclude them; when the mandatory set alone exceeds
    ``max_active`` it is activated in full (a documented exception, never silent —
    the engine notes it). The remaining accepted branches stay ``proposed`` (queued)
    and are activated in REALLOCATE when a slot frees up.
    """
    if max_active <= 0:
        return []
    ordered = sorted(accepted, key=lambda b: (-b.priority, b.branch_id))
    must = mandatory_branches(accepted, mode=mode, coverage_insufficient=coverage_insufficient)
    chosen: list[BranchRecord] = list(must)
    chosen_ids = {b.branch_id for b in chosen}
    for branch in ordered:
        if len(chosen) >= max_active:
            break
        if branch.branch_id not in chosen_ids:
            chosen.append(branch)
            chosen_ids.add(branch.branch_id)
    return sorted(chosen, key=lambda b: (-b.priority, b.branch_id))


# --------------------------------------------------------------------------------------
# the LLM strategist's items (parsing and the prompt live in workers/strategist.py)
# --------------------------------------------------------------------------------------


def proposals_from_items(
    items: Sequence[dict[str, object]], ctx: PortfolioContext, *, start_index: int
) -> tuple[list[BranchRecord], list[str]]:
    """Validate strategist items into branch proposals; invalid ones become notes."""
    from opentorus.campaign.workers.strategist import KIND_ALIASES, RELATION_ALIASES

    out: list[BranchRecord] = []
    notes: list[str] = []
    for n, item in enumerate(items, start=1):
        kind = KIND_ALIASES.get(str(item.get("kind", "")).strip().lower())
        objective = str(item.get("objective", "")).strip()
        title = str(item.get("title", "")).strip() or (kind.value if kind else f"proposal {n}")
        if kind is None or not objective:
            notes.append(f"strategist item {n} skipped: unknown kind or empty objective")
            continue
        relation = RELATION_ALIASES.get(str(item.get("root_relation", "")).strip().lower())
        if relation is None:
            relation = RootRelation.unknown
            notes.append(f"strategist item {n} ({title}): root relation unknown")
        raw_ctx = item.get("assumption_context")
        assumption_context = (
            [str(a) for a in raw_ctx if str(a).strip()]
            if isinstance(raw_ctx, list)
            else list(ctx.problem.assumptions)
        )
        out.append(
            _make_branch(
                campaign_id=ctx.campaign_id,
                branch_id=ids.branch_id(start_index + len(out)),
                title=title[:120],
                kind=kind,
                objective=objective,
                strategy_summary=str(item.get("strategy_summary", "")).strip(),
                root_relation=relation,
                assumption_context=assumption_context,
                index=len(out),
                strategy_key=None,
                distinctness_note=str(item.get("why_distinct", "")).strip(),
            )
        )
    return out, notes


def generate_portfolio(runtime: WorkerRuntime | None, ctx: PortfolioContext) -> PortfolioProposal:
    """Proposals → dedup → cap → activation, with the strategist consulted when a real
    provider is available.

    ``runtime`` may be ``None`` (pure template path). With a runtime whose leased
    provider is the mock (``provider.name == "mock"``) the template is used directly.
    With a real provider the strategist (task class ``campaign_strategy``) is asked for
    JSON; an unusable answer falls back to the template with a note. The mandatory
    rules (proof + counterexample in prove-or-refute; literature while coverage is
    insufficient) are applied to the LLM's list too — a missing mandatory branch is
    appended from the template.
    """
    n = ctx.initial_branches + PORTFOLIO_SLACK
    start = ctx.branch_counter + 1
    notes: list[str] = []
    source = "template"
    proposals: list[BranchRecord] = []
    if runtime is not None:
        from opentorus.campaign.workers.strategist import propose_with_model

        llm_items, llm_notes = propose_with_model(runtime, ctx)
        notes.extend(llm_notes)
        if llm_items:
            proposals, item_notes = proposals_from_items(llm_items, ctx, start_index=start)
            notes.extend(item_notes)
            source = "llm"
    if len(proposals) < 2:
        if source == "llm":
            notes.append(
                "strategist answer yielded fewer than two usable proposals; template fallback"
            )
            source = "template-fallback"
        proposals = template_portfolio(
            ctx.mode,
            n,
            problem=ctx.problem,
            coverage=ctx.coverage_insufficient,
            campaign_id=ctx.campaign_id,
            critical=ctx.critical_categories,
            start_index=start,
        )
    else:
        # The mandatory rules apply to a model's list too: append what it forgot.
        template = template_portfolio(
            ctx.mode,
            n,
            problem=ctx.problem,
            coverage=ctx.coverage_insufficient,
            campaign_id=ctx.campaign_id,
            critical=ctx.critical_categories,
            start_index=start + len(proposals),
        )
        have = {b.kind for b in proposals}
        needed: list[BranchKind] = []
        if CampaignMode(str(ctx.mode)) is CampaignMode.prove_or_refute:
            needed += [BranchKind.proof, BranchKind.counterexample]
        if ctx.coverage_insufficient:
            needed.append(BranchKind.literature)
        for kind in needed:
            if kind in have:
                continue
            extra = next((b for b in template if b.kind is kind), None)
            if extra is not None:
                proposals.append(
                    extra.model_copy(
                        update={
                            "branch_id": ids.branch_id(start + len(proposals)),
                            "priority": initial_priority(len(proposals)),
                        }
                    )
                )
                have.add(kind)
                notes.append(f"template {kind.value} branch appended: the strategist omitted it")
    dedup = dedup_proposals(proposals)
    capped = cap_proposals(
        dedup.accepted,
        initial_branches=ctx.initial_branches,
        mode=ctx.mode,
        coverage_insufficient=ctx.coverage_insufficient,
    )
    activated = activate_initial(
        capped.accepted,
        max_active=ctx.max_active_branches,
        mode=ctx.mode,
        coverage_insufficient=ctx.coverage_insufficient,
    )
    if len(activated) > ctx.max_active_branches:
        notes.append(
            f"{len(activated)} branches activated (mandatory routes exceed "
            f"max_active_branches={ctx.max_active_branches})"
        )
    if len(capped.accepted) > ctx.initial_branches:
        notes.append(
            f"{len(capped.accepted)} branches kept (mandatory routes exceed "
            f"initial_branches={ctx.initial_branches})"
        )
    return PortfolioProposal(
        accepted=capped.accepted,
        rejected=[*dedup.rejected, *capped.rejected],
        activated=activated,
        notes=notes,
        source=source,
    )


# --------------------------------------------------------------------------------------
# the M3 bootstrap (kept: the single-literature-branch helper)
# --------------------------------------------------------------------------------------


def bootstrap_portfolio(
    snapshot: CampaignSnapshot,
    *,
    mode: CampaignMode,
    coverage: list[str] | None = None,
) -> list[BranchRecord]:
    """Exactly one literature branch (``supporting``), priority 1.0.

    The M3 bootstrap, kept as the minimal portfolio for callers that only want the
    literature map (the survey/insufficient-coverage helper). Its objective names the
    insufficient critical coverage categories, so the branch is a real task for the
    librarian and not a placeholder. Returns a proposal with the next ``BRANCH-`` id
    from the snapshot's counter and status ``proposed``.
    """
    insufficient = list(coverage or [])
    what = ", ".join(insufficient) if insufficient else "all critical categories"
    branch_id = ids.mint(snapshot.counters, ids.BRANCH_PREFIX)
    return [
        BranchRecord(
            branch_id=branch_id,
            campaign_id=snapshot.campaign_id,
            title="Literature map",
            kind=BranchKind.literature,
            objective=f"Map the literature for {snapshot.problem_id}: {what}",
            strategy_summary=(
                "Assess category coverage from local artifacts (papers, known results, "
                "theorem references); coverage stays at most partial until a reviewed "
                "theorem reference exists."
            ),
            root_relation=RootRelation.supporting,
            status=BranchStatus.proposed,
            priority=1.0,
            assigned_worker_role=WorkerRole.librarian,
            strategy_key="literature_map",
            estimated_cost=1.0,
        )
    ]


__all__ = [
    "COVERAGE_HINTS",
    "JACCARD_DUPLICATE_THRESHOLD",
    "KIND_TO_ROLE",
    "PORTFOLIO_SLACK",
    "STRATEGY_TITLES",
    "DedupResult",
    "PortfolioContext",
    "PortfolioProposal",
    "activate_initial",
    "bootstrap_portfolio",
    "cap_proposals",
    "dedup_proposals",
    "generate_portfolio",
    "initial_priority",
    "jaccard",
    "mandatory_branches",
    "normalize_objective",
    "proposals_from_items",
    "template_portfolio",
]
