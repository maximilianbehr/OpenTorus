"""Theorem references (THMREF): store, locators, heuristic extraction, relations."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.papers import acquire_paper, read_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.research.theorems import store
from opentorus.research.theorems.extraction import extract_heuristic, parse_statement
from opentorus.research.theorems.locators import (
    clip_excerpt,
    located_context,
    location_hash,
    validate_locator,
)
from opentorus.research.theorems.models import SourceLocator, TheoremReference
from opentorus.research.theorems.relations import (
    add_relation,
    contradicting_refs,
    relation_graph,
)
from opentorus.workspace import init_workspace

PAGES = [
    "1 Introduction\nWe study finite groups. By Theorem 2.1 we get the bound.\n",
    (
        "2 Main results\n"
        "Theorem 2.1 (Main theorem). Let G be a finite group of order n. "
        "Then every element of G has order dividing n.\n"
        "Proof. Omitted.\n"
        "Lemma 2.2. Suppose H is a subgroup of G. Then |H| divides |G|.\n"
        "Proposition 2.3. There exists a group of order 6 that is not abelian.\n"
    ),
]


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return tmp_path / ".opentorus"


def _paper(ot: Path, pages: list[str] | None = None, *, arxiv_id: str = "2401.00001") -> str:
    record = SourceRecord(source="arxiv", title="Finite groups", arxiv_id=arxiv_id)
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    read_paper(ot, paper.id, page_extractor=lambda p: list(pages or PAGES))
    return paper.id


def _ref(paper_id: str, label: str = "Theorem 2.1", **kw) -> TheoremReference:
    return TheoremReference(
        paper_id=paper_id,
        locator=SourceLocator(paper_id=paper_id, label=label),
        theorem_label=label,
        **kw,
    )


# --- store ------------------------------------------------------------------------


def test_add_reference_requires_existing_local_paper(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    with pytest.raises(OpenTorusError, match="no local paper"):
        store.add_reference(ot, _ref("PAPER-0042"))
    assert store.list_references(ot) == []


def test_ids_are_sequential_and_ledger_is_workspace_level(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    a = store.add_reference(ot, _ref(pid, "Theorem 2.1", problem_id="problem-0001"))
    b = store.add_reference(ot, _ref(pid, "Lemma 2.2"))
    assert (a.id, b.id) == ("THMREF-0001", "THMREF-0002")
    assert a.problem_id == "PROBLEM-0001"
    assert (ot / "theorems" / "references.jsonl").is_file()
    assert [r.id for r in store.list_references(ot, problem_id="PROBLEM-0001")] == [a.id]
    assert [r.id for r in store.list_references(ot, paper_id=pid)] == [a.id, b.id]
    assert store.get_reference(ot, "thmref-0002") is not None


def test_new_reference_cannot_be_born_accepted(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    with pytest.raises(OpenTorusError, match="cannot be created as 'accepted'"):
        store.add_reference(ot, _ref(pid, review_status="accepted"))


def test_set_review_status_is_the_only_path_to_accepted(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    ref = store.add_reference(ot, _ref(pid))
    assert ref.review_status == "candidate"
    with pytest.raises(OpenTorusError, match="Unknown review status"):
        store.set_review_status(ot, ref.id, "verified")
    updated = store.set_review_status(ot, ref.id, "accepted", "checked against p.3")
    assert updated.review_status == "accepted"
    assert updated.review_note == "checked against p.3"
    again = store.get_reference(ot, ref.id)
    assert again is not None and again.review_status == "accepted"
    assert [r.id for r in store.list_references(ot, review_status="accepted")] == [ref.id]
    with pytest.raises(OpenTorusError, match="No theorem reference"):
        store.set_review_status(ot, "THMREF-0099", "rejected")


def test_review_can_classify_categories_relation_and_problem(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    ref = store.add_reference(ot, _ref(pid))
    assert ref.categories == [] and ref.problem_id is None
    updated = store.set_review_status(
        ot,
        ref.id,
        "accepted",
        "classified",
        categories=["strongest_known_positive_results", "standard_tools_lemmas"],
        root_relation="supporting",
        problem_id="problem-0001",
    )
    assert [c.value for c in updated.categories] == [
        "strongest_known_positive_results",
        "standard_tools_lemmas",
    ]
    assert updated.root_relation == "supporting" and updated.problem_id == "PROBLEM-0001"
    # None leaves the classification untouched.
    again = store.set_review_status(ot, ref.id, "candidate", "re-check")
    assert again.categories == updated.categories and again.problem_id == "PROBLEM-0001"
    with pytest.raises(OpenTorusError, match="Unknown coverage category"):
        store.set_review_status(ot, ref.id, "accepted", categories=["vibes"])
    with pytest.raises(OpenTorusError, match="Unknown root relation"):
        store.set_review_status(ot, ref.id, "accepted", root_relation="sideways")


def test_excerpt_limit_is_enforced_by_the_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at most 300"):
        _ref("PAPER-0001", excerpt="x" * 301)
    assert len(clip_excerpt("word " * 200)) <= 300
    assert clip_excerpt("word " * 200).endswith("...")
    assert clip_excerpt("short  text ") == "short text"


def test_root_relation_must_be_a_known_value() -> None:
    with pytest.raises(ValueError, match="unknown root_relation"):
        _ref("PAPER-0001", root_relation="sideways")
    assert _ref("PAPER-0001", root_relation="special-case").root_relation == "special-case"


# --- locators ---------------------------------------------------------------------


def test_validate_locator_ok_and_context(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    v = validate_locator(
        ot, SourceLocator(paper_id=pid, label="Theorem 2.1", page=2, section="Main results")
    )
    assert v.ok, v.errors
    assert v.page_checked and v.section_checked
    assert v.context is not None and v.context.startswith("Theorem 2.1 (Main theorem)")
    # Context is cut before the next environment: Lemma 2.2 does not leak in.
    assert "Lemma 2.2" not in v.context


def test_validate_locator_errors(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    unknown = validate_locator(ot, SourceLocator(paper_id="PAPER-0042", label="Theorem 1"))
    assert not unknown.ok and "unknown paper" in unknown.errors[0]

    missing = validate_locator(ot, SourceLocator(paper_id=pid, label="Theorem 9.9"))
    assert not missing.ok
    assert "does not contain a numbered result 9.9" in missing.errors[0]
    assert "2.1, 2.2, 2.3" in missing.errors[0]

    wrong_kind = validate_locator(ot, SourceLocator(paper_id=pid, label="Lemma 2.1"))
    assert not wrong_kind.ok and "not as 'Lemma 2.1'" in wrong_kind.errors[0]

    beyond = validate_locator(ot, SourceLocator(paper_id=pid, label="Theorem 2.1", page=9))
    assert not beyond.ok and "page 9 is outside" in beyond.errors[0]
    assert beyond.page_checked

    bad_section = validate_locator(
        ot, SourceLocator(paper_id=pid, label="Theorem 2.1", section="Appendix Z")
    )
    assert not bad_section.ok and "section 'Appendix Z' not found" in bad_section.errors[0]


def test_validate_locator_warns_when_it_cannot_decide(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    # A corpus without any numbered environment: a label can be neither confirmed
    # nor refuted -> warning, ok stays True.
    pid = _paper(ot, ["1 Introduction\nWe discuss groups without numbering.\n"])
    v = validate_locator(ot, SourceLocator(paper_id=pid, label="Theorem 3.1"))
    assert v.ok
    assert any("no extractable numbering" in w for w in v.warnings)

    # Unparsed paper (metadata only): label/page unverifiable, never invented.
    from opentorus.research.papers import add_paper

    stub = add_paper(ot, "https://arxiv.org/abs/2402.00002")
    v2 = validate_locator(ot, SourceLocator(paper_id=stub.id, label="Theorem 1", page=3))
    assert v2.ok
    assert any(w.startswith("unparsed") for w in v2.warnings)
    assert any("page 3 unverifiable" in w for w in v2.warnings)
    assert not v2.page_checked


def test_located_context_and_hash_are_reproducible(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    loc = SourceLocator(paper_id=pid, label="Theorem 2.1")
    ctx = located_context(ot, loc)
    assert ctx is not None
    # The statement occurrence (in the full body) is chosen over the citation
    # "By Theorem 2.1 we get" in the introduction.
    assert ctx.startswith("Theorem 2.1 (Main theorem). Let G be a finite group")
    assert location_hash(ctx) == location_hash(located_context(ot, loc) or "")
    assert location_hash("a  b") == location_hash("a b")
    assert located_context(ot, SourceLocator(paper_id=pid, label="Theorem 9.9")) is None
    assert located_context(ot, SourceLocator(paper_id=pid)) is None


# --- extraction -------------------------------------------------------------------


def test_heuristic_extraction_creates_located_candidates(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    refs = extract_heuristic(ot, pid, problem_id="PROBLEM-0001")
    labels = [r.theorem_label for r in refs]
    assert labels == ["Theorem 2.1", "Lemma 2.2", "Proposition 2.3"]
    for ref in refs:
        assert ref.review_status == "candidate"
        assert ref.extraction_method == "heuristic"
        assert ref.problem_id == "PROBLEM-0001"
        assert len(ref.location_hash) == 64
        assert 0 < len(ref.excerpt) <= 300
        assert ref.excerpt.startswith(ref.theorem_label or "")
        assert ref.locator.label == ref.theorem_label
        assert location_hash(located_context(ot, ref.locator) or "") == ref.location_hash
    thm = refs[0]
    assert thm.title == "Main theorem"
    assert thm.assumptions == ["Let G be a finite group of order n."]
    assert thm.conclusion == "every element of G has order dividing n."
    assert any(q.lower().startswith("every element") for q in thm.quantifiers)
    prop = refs[2]
    assert prop.assumptions == []
    assert any(q.lower().startswith("there exists") for q in prop.quantifiers)
    # Idempotent: a second run adds nothing (dedupe by paper + label).
    assert extract_heuristic(ot, pid) == []
    assert len(store.list_references(ot, paper_id=pid)) == 3


def test_heuristic_candidates_carry_category_hints_and_stay_partial(tmp_path: Path) -> None:
    """A candidate is filed under a coverage category read off its label family and
    statement (Theorem -> strongest positive, Lemma/Proposition -> tools, a stated
    non-existence -> negative, a named counterexample -> counterexamples), so coverage
    can show ``partial`` for it; ``adequate`` still needs review."""
    from opentorus.research.theorems.coverage import assess_coverage
    from opentorus.research.theorems.extraction import infer_categories
    from opentorus.research.theorems.models import CoverageCategory, CoverageLevel

    ot = _ot(tmp_path)
    pid = _paper(ot)
    refs = extract_heuristic(ot, pid, problem_id="PROBLEM-0001")
    assert [[c.value for c in r.categories] for r in refs] == [
        ["strongest_known_positive_results"],
        ["standard_tools_lemmas"],
        ["standard_tools_lemmas"],
    ]
    assert infer_categories("Theorem 3", "There is no Hadamard matrix of order 6.") == [
        CoverageCategory.known_negative_results
    ]
    assert infer_categories("Corollary 4", "The Petersen graph is a counterexample.") == [
        CoverageCategory.known_counterexamples
    ]
    assert infer_categories("Proposition 5", "There is no such group.") == [
        CoverageCategory.standard_tools_lemmas
    ]
    cov = assess_coverage(ot, "PROBLEM-0001", persist=False)
    positive = cov.entries[CoverageCategory.strongest_known_positive_results.value]
    assert positive.level is CoverageLevel.partial and positive.evidence_ids == [refs[0].id]
    tools = cov.entries[CoverageCategory.standard_tools_lemmas.value]
    assert tools.level is CoverageLevel.partial and sorted(tools.evidence_ids) == sorted(
        r.id for r in refs[1:]
    )
    assert all(e.level is not CoverageLevel.adequate for e in cov.entries.values())
    # review replaces the hint: an accepted, re-classified reference is what makes adequate
    store.set_review_status(
        ot, refs[0].id, "accepted", "checked", categories=["equivalent_formulations"]
    )
    cov2 = assess_coverage(ot, "PROBLEM-0001", persist=False)
    assert cov2.entries["equivalent_formulations"].level is CoverageLevel.adequate
    assert cov2.entries[positive.category.value].level is CoverageLevel.missing


def test_heuristic_extraction_needs_parsed_text(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    from opentorus.research.papers import add_paper

    stub = add_paper(ot, "https://arxiv.org/abs/2402.00002")
    with pytest.raises(OpenTorusError, match="no parsed full text"):
        extract_heuristic(ot, stub.id)
    with pytest.raises(OpenTorusError, match="No paper"):
        extract_heuristic(ot, "PAPER-0099")


def test_parse_statement_if_then_split() -> None:
    parsed = parse_statement(
        "Corollary 3.4. If n is prime, then Z/nZ is a field. For all k the map is injective.",
        "Corollary 3.4",
    )
    assert parsed["assumptions"] == ["If n is prime."]
    assert parsed["conclusion"] == "Z/nZ is a field."
    assert any(q.lower().startswith("for all k") for q in parsed["quantifiers"])


# --- relations --------------------------------------------------------------------


def test_relations_keep_provenance_and_review_status(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    a = store.add_reference(ot, _ref(pid, "Theorem 2.1"))
    b = store.add_reference(ot, _ref(pid, "Lemma 2.2"))
    rel = add_relation(ot, a.id, b.id, "implies", provenance="llm", rationale="model guess")
    assert rel.id == "THMREL-0001"
    assert rel.provenance == "llm" and rel.review_status == "candidate"
    assert rel.rationale == "model guess"
    human = add_relation(
        ot, b.id, a.id, "contradicts", provenance="manual", review_status="accepted"
    )
    assert human.id == "THMREL-0002" and human.review_status == "accepted"
    graph = relation_graph(ot)
    assert [r.id for r in graph[a.id]] == [rel.id]
    assert contradicting_refs(ot, a.id) == [b.id]
    assert contradicting_refs(ot, b.id) == [a.id]
    assert [r.id for r in store.list_relations(ot, ref_id=a.id)] == [rel.id, human.id]


def test_relation_validation(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = _paper(ot)
    a = store.add_reference(ot, _ref(pid, "Theorem 2.1"))
    with pytest.raises(OpenTorusError, match="Unknown relation"):
        add_relation(ot, a.id, a.id, "refutes", provenance="manual")
    with pytest.raises(OpenTorusError, match="No theorem reference"):
        add_relation(ot, a.id, "THMREF-0077", "implies", provenance="manual")
    with pytest.raises(OpenTorusError, match="No theorem reference"):
        add_relation(ot, a.id, "CLAIM-0001", "implies", provenance="manual")
    # applies-to may target a dossier claim / campaign obligation id.
    rel = add_relation(ot, a.id, "claim-0001", "applies-to", provenance="manual")
    assert rel.target_ref == "CLAIM-0001"
    with pytest.raises(OpenTorusError, match="distinct"):
        add_relation(ot, a.id, a.id, "implies", provenance="manual")
