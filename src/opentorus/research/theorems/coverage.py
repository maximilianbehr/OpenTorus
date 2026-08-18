"""Category-based literature coverage for a problem.

Coverage is a map ``category -> level`` derived from *what the workspace can
show*, never from how many papers it holds: an accepted THMREF tagged with a
category makes it ``adequate``; candidate-only references make it ``partial``;
dossier facts (related papers, known results, legacy THM-* refs) contribute at
most ``partial``; a human override (``theorem coverage --set``) wins; two
accepted references in one category linked by ``contradicts`` yield
``conflicting``. ``insufficient`` = the mode's critical categories that are still
``unknown`` or ``missing`` — that is what the campaign scheduler boosts literature
work on. Ten registered papers with no categorised references leave every
category insufficient by construction.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.theorems import store
from opentorus.research.theorems.models import (
    CoverageAssessment,
    CoverageCategory,
    CoverageEntry,
    CoverageLevel,
    TheoremReference,
    TheoremRelationKind,
)

_PROVE_OR_REFUTE: tuple[CoverageCategory, ...] = (
    CoverageCategory.original_problem_source,
    CoverageCategory.definitions_notation,
    CoverageCategory.strongest_known_positive_results,
    CoverageCategory.known_negative_results,
    CoverageCategory.known_counterexamples,
    CoverageCategory.equivalent_formulations,
    CoverageCategory.standard_tools_lemmas,
)
_EXPLORATION: tuple[CoverageCategory, ...] = (
    CoverageCategory.original_problem_source,
    CoverageCategory.definitions_notation,
    CoverageCategory.special_cases,
    CoverageCategory.standard_tools_lemmas,
)
_SURVEY: tuple[CoverageCategory, ...] = tuple(CoverageCategory)

INSUFFICIENT_LEVELS = frozenset({CoverageLevel.unknown, CoverageLevel.missing})


def critical_categories(mode: str | None) -> list[CoverageCategory]:
    """Categories that must be covered for a campaign mode (``None`` = prove-or-refute)."""
    if mode is None or mode == "prove-or-refute":
        return list(_PROVE_OR_REFUTE)
    if mode == "exploration":
        return list(_EXPLORATION)
    if mode == "survey":
        return list(_SURVEY)
    return list(_PROVE_OR_REFUTE)


def _dossier_signals(ot_dir: Path, problem_id: str) -> dict[CoverageCategory, list[str]]:
    """Dossier facts that count as *partial* coverage (derived), keyed by category."""
    from opentorus.research.dossier import store as dossier_store

    signals: dict[CoverageCategory, list[str]] = {}
    if dossier_store.get_dossier(ot_dir, problem_id) is None:
        return signals
    related = [
        p.id for p in dossier_store.list_related_papers(ot_dir, problem_id) if p.paper_artifact
    ]
    if related:
        signals[CoverageCategory.original_problem_source] = related
    known = [k.id for k in dossier_store.list_known_results(ot_dir, problem_id)]
    if known:
        signals[CoverageCategory.strongest_known_positive_results] = known
    thm = [t.id for t in dossier_store.list_theorem_refs(ot_dir, problem_id)]
    if thm:
        signals[CoverageCategory.standard_tools_lemmas] = thm
    return signals


def _contradicting_pair(ot_dir: Path, refs: list[TheoremReference]) -> bool:
    ids = {r.id.upper() for r in refs}
    if len(ids) < 2:
        return False
    for rel in store.list_relations(ot_dir):
        if rel.relation is not TheoremRelationKind.contradicts or rel.review_status == "rejected":
            continue
        if rel.source_ref.upper() in ids and rel.target_ref.upper() in ids:
            return True
    return False


def assess_coverage(
    ot_dir: Path,
    problem_id: str,
    *,
    mode: str | None = None,
    campaign_id: str | None = None,
    persist: bool = True,
) -> CoverageAssessment:
    """Derive the coverage map for ``problem_id`` (and append it to the ledger)."""
    pid = problem_id.strip().upper()
    all_refs = store.list_references(ot_dir, problem_id=pid)
    accepted = [r for r in all_refs if r.review_status == "accepted"]
    candidates = [r for r in all_refs if r.review_status == "candidate"]
    dossier_signals = _dossier_signals(ot_dir, pid)
    overrides = store.list_coverage_overrides(ot_dir, pid)
    # A rejected reference still shows literature work happened: uncovered
    # categories are then "missing" rather than "unknown".
    any_signal = bool(all_refs or dossier_signals or overrides)

    entries: dict[str, CoverageEntry] = {}
    for category in CoverageCategory:
        override = overrides.get(category.value)
        if override is not None:
            entries[category.value] = override
            continue
        acc = [r for r in accepted if category in r.categories]
        cand = [r for r in candidates if category in r.categories]
        if acc and _contradicting_pair(ot_dir, acc):
            entries[category.value] = CoverageEntry(
                category=category,
                level=CoverageLevel.conflicting,
                evidence_ids=[r.id for r in acc],
                provenance="derived",
                note="accepted references in this category contradict each other",
            )
        elif acc:
            entries[category.value] = CoverageEntry(
                category=category,
                level=CoverageLevel.adequate,
                evidence_ids=[r.id for r in acc],
                provenance="derived",
                note="accepted theorem reference(s)",
            )
        elif cand:
            entries[category.value] = CoverageEntry(
                category=category,
                level=CoverageLevel.partial,
                evidence_ids=[r.id for r in cand],
                provenance="derived",
                note="candidate theorem reference(s) only; review to make adequate",
            )
        elif category in dossier_signals:
            entries[category.value] = CoverageEntry(
                category=category,
                level=CoverageLevel.partial,
                evidence_ids=dossier_signals[category],
                provenance="derived",
                note="dossier facts only (at most partial without a reviewed theorem reference)",
            )
        else:
            entries[category.value] = CoverageEntry(
                category=category,
                level=CoverageLevel.missing if any_signal else CoverageLevel.unknown,
                provenance="derived",
                note="no categorised reference" if any_signal else "no literature signal yet",
            )

    critical = critical_categories(mode)
    insufficient = [c for c in critical if entries[c.value].level in INSUFFICIENT_LEVELS]
    assessment = CoverageAssessment(
        problem_id=pid,
        campaign_id=campaign_id,
        mode=mode,
        entries=entries,
        critical_categories=critical,
        insufficient=insufficient,
    )
    if persist:
        return store.record_coverage(ot_dir, assessment)
    return assessment
