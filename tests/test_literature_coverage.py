"""Category-based literature coverage: levels come from reviewed references and
human judgement, never from how many papers are registered."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.dossier import store as dossier_store
from opentorus.research.papers import acquire_paper, add_paper, read_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.research.theorems import store
from opentorus.research.theorems.coverage import assess_coverage, critical_categories
from opentorus.research.theorems.models import (
    CoverageCategory,
    CoverageLevel,
    SourceLocator,
    TheoremReference,
)
from opentorus.research.theorems.relations import add_relation
from opentorus.workspace import init_workspace

PAGES = [
    "1 Introduction\nTheorem 1.1. Let G be a finite group. Then G is finite.\n"
    "Theorem 1.2. Let G be a finite group. Then G is not infinite.\n"
]
POS = CoverageCategory.strongest_known_positive_results


def _setup(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    ot = tmp_path / ".opentorus"
    record = SourceRecord(source="arxiv", title="Finite groups", arxiv_id="2401.00001")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    read_paper(ot, paper.id, page_extractor=lambda p: list(PAGES))
    dossier_store.create_dossier(ot, "Is every finite group finite?")
    return ot, paper.id


def _ref(paper_id: str, label: str, categories: list[CoverageCategory]) -> TheoremReference:
    return TheoremReference(
        paper_id=paper_id,
        locator=SourceLocator(paper_id=paper_id, label=label),
        theorem_label=label,
        problem_id="PROBLEM-0001",
        categories=categories,
    )


def test_critical_categories_per_mode() -> None:
    prove = critical_categories("prove-or-refute")
    assert prove == critical_categories(None)
    assert CoverageCategory.known_counterexamples in prove
    assert CoverageCategory.special_cases not in prove
    explore = critical_categories("exploration")
    assert explore == [
        CoverageCategory.original_problem_source,
        CoverageCategory.definitions_notation,
        CoverageCategory.special_cases,
        CoverageCategory.standard_tools_lemmas,
    ]
    assert len(critical_categories("survey")) == 11
    assert critical_categories("bogus") == prove


def test_no_signal_is_unknown_and_all_critical_insufficient(tmp_path: Path) -> None:
    ot, _pid = _setup(tmp_path)
    cov = assess_coverage(ot, "PROBLEM-0001", mode="prove-or-refute")
    assert cov.id == "COV-0001"
    assert set(cov.entries) == {c.value for c in CoverageCategory}
    assert all(e.level is CoverageLevel.unknown for e in cov.entries.values())
    assert cov.insufficient == critical_categories("prove-or-refute")
    assert store.latest_coverage(ot, "PROBLEM-0001") is not None
    assert store.latest_coverage(ot, "PROBLEM-0001").id == "COV-0001"  # type: ignore[union-attr]
    # persist=False leaves the ledger alone.
    again = assess_coverage(ot, "PROBLEM-0001", persist=False)
    assert again.id == ""
    assert len(store.list_coverage_history(ot, "PROBLEM-0001")) == 1


def test_paper_count_never_raises_a_level(tmp_path: Path) -> None:
    ot, _pid = _setup(tmp_path)
    for i in range(10):
        add_paper(ot, f"https://arxiv.org/abs/2402.{i:05d}")
    from opentorus.research.papers import list_papers

    assert len(list_papers(ot)) >= 10
    cov = assess_coverage(ot, "PROBLEM-0001", mode="prove-or-refute")
    assert cov.insufficient == critical_categories("prove-or-refute")
    assert not any(e.level is CoverageLevel.adequate for e in cov.entries.values())


def test_candidate_partial_accepted_adequate(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    ref = store.add_reference(ot, _ref(pid, "Theorem 1.1", [POS]))
    cov = assess_coverage(ot, "PROBLEM-0001")
    assert cov.entries[POS.value].level is CoverageLevel.partial
    assert cov.entries[POS.value].evidence_ids == [ref.id]
    # Other categories are now 'missing' (there is a signal, just not for them).
    assert cov.entries[CoverageCategory.known_counterexamples.value].level is CoverageLevel.missing
    assert POS not in cov.insufficient  # partial is not insufficient
    store.set_review_status(ot, ref.id, "accepted", "verified against source")
    cov2 = assess_coverage(ot, "PROBLEM-0001")
    assert cov2.entries[POS.value].level is CoverageLevel.adequate
    assert cov2.id == "COV-0002"
    # Rejected references contribute nothing.
    store.set_review_status(ot, ref.id, "rejected", "wrong statement")
    cov3 = assess_coverage(ot, "PROBLEM-0001")
    assert cov3.entries[POS.value].level is CoverageLevel.missing


def test_dossier_facts_are_at_most_partial(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    dossier_store.add_related_paper(ot, "PROBLEM-0001", title="Origin", paper_artifact=pid)
    dossier_store.add_known_result(ot, "PROBLEM-0001", "G is finite.", source_artifacts=[pid])
    dossier_store.add_theorem_ref(ot, "PROBLEM-0001", paper_artifact=pid, theorem_number="1.1")
    cov = assess_coverage(ot, "PROBLEM-0001", mode="exploration")
    e = cov.entries
    assert e[CoverageCategory.original_problem_source.value].level is CoverageLevel.partial
    assert e[POS.value].level is CoverageLevel.partial
    assert e[CoverageCategory.standard_tools_lemmas.value].level is CoverageLevel.partial
    assert e[CoverageCategory.definitions_notation.value].level is CoverageLevel.missing
    assert cov.insufficient == [
        CoverageCategory.definitions_notation,
        CoverageCategory.special_cases,
    ]


def test_human_override_wins_and_is_persisted(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    ref = store.add_reference(ot, _ref(pid, "Theorem 1.1", [POS]))
    store.set_review_status(ot, ref.id, "accepted")
    store.set_coverage_override(
        ot, "PROBLEM-0001", POS.value, "missing", evidence_ids=[], note="statement is off-topic"
    )
    store.set_coverage_override(
        ot,
        "PROBLEM-0001",
        CoverageCategory.definitions_notation.value,
        "adequate",
        evidence_ids=[pid],
        note="section 2 defines everything",
    )
    cov = assess_coverage(ot, "PROBLEM-0001", mode="prove-or-refute")
    assert cov.entries[POS.value].level is CoverageLevel.missing
    assert cov.entries[POS.value].provenance == "human"
    assert POS in cov.insufficient
    defs = cov.entries[CoverageCategory.definitions_notation.value]
    assert defs.level is CoverageLevel.adequate and defs.evidence_ids == [pid]
    # Latest override per category wins.
    store.set_coverage_override(ot, "PROBLEM-0001", POS.value, "adequate", note="re-checked")
    cov2 = assess_coverage(ot, "PROBLEM-0001", mode="prove-or-refute")
    assert cov2.entries[POS.value].level is CoverageLevel.adequate
    assert POS not in cov2.insufficient
    lines = (ot / "theorems" / "coverage" / "PROBLEM-0001.jsonl").read_text().splitlines()
    assert len(lines) == 5  # 3 overrides + 2 assessments, append-only
    with pytest.raises(OpenTorusError, match="Unknown coverage category"):
        store.set_coverage_override(ot, "PROBLEM-0001", "vibes", "adequate")
    with pytest.raises(OpenTorusError, match="Unknown coverage level"):
        store.set_coverage_override(ot, "PROBLEM-0001", POS.value, "great")


def test_contradicting_accepted_references_are_conflicting(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    a = store.add_reference(ot, _ref(pid, "Theorem 1.1", [POS]))
    b = store.add_reference(ot, _ref(pid, "Theorem 1.2", [POS]))
    add_relation(ot, a.id, b.id, "contradicts", provenance="manual", rationale="disagree")
    # Candidates only -> partial, no conflict yet.
    assert assess_coverage(ot, "PROBLEM-0001").entries[POS.value].level is CoverageLevel.partial
    store.set_review_status(ot, a.id, "accepted")
    assert assess_coverage(ot, "PROBLEM-0001").entries[POS.value].level is CoverageLevel.adequate
    store.set_review_status(ot, b.id, "accepted")
    cov = assess_coverage(ot, "PROBLEM-0001")
    entry = cov.entries[POS.value]
    assert entry.level is CoverageLevel.conflicting
    assert set(entry.evidence_ids) == {a.id, b.id}
    assert POS not in cov.insufficient  # conflicting is a signal to resolve, not "missing"


def test_campaign_id_and_mode_are_recorded(tmp_path: Path) -> None:
    ot, _pid = _setup(tmp_path)
    cov = assess_coverage(ot, "problem-0001", mode="survey", campaign_id="CAMPAIGN-0001")
    assert cov.problem_id == "PROBLEM-0001"
    assert cov.campaign_id == "CAMPAIGN-0001" and cov.mode == "survey"
    assert len(cov.critical_categories) == 11
