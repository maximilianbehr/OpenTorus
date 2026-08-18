"""Deterministic applicability checks (THMAPP) — typed results, never promotions."""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import claims as dossier_claims
from opentorus.research.dossier import store as dossier_store
from opentorus.research.papers import acquire_paper, read_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.research.theorems import store
from opentorus.research.theorems.applicability import check_applicability
from opentorus.research.theorems.extraction import extract_heuristic
from opentorus.research.theorems.models import ApplicabilityResult, TheoremReference
from opentorus.research.theorems.relations import add_relation
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
CLAIM = "Every element of G has order dividing n."
CONTEXT = ["G is a finite group of order n"]


def _setup(tmp_path: Path) -> tuple[Path, str, list[TheoremReference]]:
    init_workspace(tmp_path)
    ot = tmp_path / ".opentorus"
    record = SourceRecord(source="arxiv", title="Finite groups", arxiv_id="2401.00001")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    read_paper(ot, paper.id, page_extractor=lambda p: list(PAGES))
    dossier_store.create_dossier(ot, "Every element of a finite group has order dividing |G|.")
    refs = extract_heuristic(ot, paper.id, problem_id="PROBLEM-0001")
    return ot, paper.id, refs


def _names(check, passed: bool | None) -> set[str]:
    return {c.name for c in check.checks if c.passed is passed}


def test_happy_path_is_accepted_and_persisted(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    thm = refs[0]
    check = check_applicability(
        ot, thm.id, problem_id="PROBLEM-0001", assumption_context=CONTEXT, claim_text=CLAIM
    )
    assert check.result is ApplicabilityResult.accepted, check.model_dump()
    assert check.id == "THMAPP-0001"
    assert check.performed_by == "deterministic"
    assert check.mismatches == []
    assert _names(check, False) == set()
    assert "statement_observed" in _names(check, True)
    assert "context_implies_hypotheses" in _names(check, True)
    assert [c.id for c in store.list_applicability_checks(ot, ref_id=thm.id)] == [check.id]
    assert (ot / "theorems" / "applicability_checks.jsonl").is_file()


def test_missing_hypotheses_is_inconclusive(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    prop = refs[2]
    assert prop.assumptions == []
    check = check_applicability(
        ot,
        prop.id,
        problem_id="PROBLEM-0001",
        assumption_context=[],
        claim_text="There exists a group of order 6 that is not abelian.",
    )
    assert check.result is ApplicabilityResult.inconclusive
    assert "hypotheses_represented" in _names(check, False)


def test_quantifier_mismatch_is_rejected(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    check = check_applicability(
        ot,
        refs[0].id,
        problem_id="PROBLEM-0001",
        assumption_context=CONTEXT,
        claim_text="There exists some element of G whose order divides n.",
    )
    assert check.result is ApplicabilityResult.rejected
    assert "quantifier_agreement" in _names(check, False)
    assert any("quantifier mismatch" in m for m in check.mismatches)


def test_domain_mismatch_is_rejected_with_named_token(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    absent = check_applicability(
        ot,
        refs[0].id,
        problem_id="PROBLEM-0001",
        assumption_context=["G is a group of order n"],
        claim_text=CLAIM,
    )
    assert absent.result is ApplicabilityResult.rejected
    assert any("'finite' required" in m and "absent" in m for m in absent.mismatches)

    contradicted = check_applicability(
        ot,
        refs[0].id,
        problem_id="PROBLEM-0001",
        assumption_context=["G is an infinite group of order n"],
        claim_text=CLAIM,
    )
    assert contradicted.result is ApplicabilityResult.rejected
    assert any("context says 'infinite'" in m for m in contradicted.mismatches)


def test_parameter_mismatch_is_rejected(tmp_path: Path) -> None:
    ot, pid, _refs = _setup(tmp_path)
    ref = store.add_reference(
        ot,
        TheoremReference(
            paper_id=pid,
            locator={"paper_id": pid, "label": "Theorem 2.1"},
            theorem_label="Theorem 2.1",
            assumptions=["Let d = 3 and let G be a finite group."],
            conclusion="G is solvable.",
            problem_id="PROBLEM-0001",
        ),
    )
    check = check_applicability(
        ot,
        ref.id,
        problem_id="PROBLEM-0001",
        assumption_context=["d = 4 and G is a finite group"],
        claim_text="G is solvable.",
    )
    assert check.result is ApplicabilityResult.rejected
    assert any("parameter 'd = 3'" in m and "'d = 4'" in m for m in check.mismatches)


def test_uncovered_hypothesis_needs_human_review(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    check = check_applicability(
        ot,
        refs[0].id,
        problem_id="PROBLEM-0001",
        assumption_context=["everything considered here is finite"],
        claim_text=CLAIM,
    )
    assert check.result is ApplicabilityResult.needs_human_review
    assert "context_implies_hypotheses" in _names(check, False)


def test_context_reference_with_implies_relation_covers_hypotheses(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    thm, lemma = refs[0], refs[1]
    add_relation(ot, lemma.id, thm.id, "implies", provenance="manual", rationale="test")
    check = check_applicability(
        ot,
        thm.id,
        problem_id="PROBLEM-0001",
        assumption_context=[lemma.id],
        claim_text="Every element of the finite group G has order dividing n.",
    )
    assert check.result is ApplicabilityResult.accepted, check.model_dump()


def test_converse_direction_is_rejected_unless_equivalent(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    thm, lemma = refs[0], refs[1]
    rejected = check_applicability(
        ot,
        thm.id,
        problem_id="PROBLEM-0001",
        assumption_context=CONTEXT,
        claim_text=CLAIM,
        direction="converse",
    )
    assert rejected.result is ApplicabilityResult.rejected
    assert "direction" in _names(rejected, False)
    add_relation(ot, thm.id, lemma.id, "equivalent-to", provenance="manual")
    licensed = check_applicability(
        ot,
        thm.id,
        problem_id="PROBLEM-0001",
        assumption_context=CONTEXT,
        claim_text=CLAIM,
        direction="converse",
    )
    assert "direction" in _names(licensed, True)
    assert licensed.result is ApplicabilityResult.accepted


def test_contradicted_by_accepted_reference_is_rejected(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    thm, other = refs[0], refs[2]
    add_relation(ot, other.id, thm.id, "contradicts", provenance="manual")
    # A *candidate* contradiction does not disqualify ...
    ok = check_applicability(
        ot, thm.id, problem_id="PROBLEM-0001", assumption_context=CONTEXT, claim_text=CLAIM
    )
    assert ok.result is ApplicabilityResult.accepted
    # ... an accepted one does.
    store.set_review_status(ot, other.id, "accepted", "human")
    bad = check_applicability(
        ot, thm.id, problem_id="PROBLEM-0001", assumption_context=CONTEXT, claim_text=CLAIM
    )
    assert bad.result is ApplicabilityResult.rejected
    assert any("contradicted by accepted" in m for m in bad.mismatches)


def test_changed_source_text_is_inconclusive(tmp_path: Path) -> None:
    ot, pid, refs = _setup(tmp_path)
    text_path = ot / "papers" / pid / "text.txt"
    text_path.write_text(
        text_path.read_text(encoding="utf-8").replace("order dividing n", "order dividing 2n"),
        encoding="utf-8",
    )
    check = check_applicability(
        ot, refs[0].id, problem_id="PROBLEM-0001", assumption_context=CONTEXT, claim_text=CLAIM
    )
    assert check.result is ApplicabilityResult.inconclusive
    assert any("source text changed" in m for m in check.mismatches)


def test_result_precedence_rejected_over_review_over_inconclusive(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    # Uncovered hypotheses (needs-human-review) AND a quantifier mismatch (rejected).
    check = check_applicability(
        ot,
        refs[0].id,
        problem_id="PROBLEM-0001",
        assumption_context=["everything considered here is finite"],
        claim_text="There exists some element whose order divides n.",
    )
    assert check.result is ApplicabilityResult.rejected
    assert "context_implies_hypotheses" in _names(check, False)


def test_accepted_check_changes_no_claim_status(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    claim = dossier_claims.add_claim(ot, "PROBLEM-0001", claim_type="CONJECTURE", statement=CLAIM)
    before = [c.model_dump(mode="json") for c in dossier_store.list_claims(ot, "PROBLEM-0001")]
    check = check_applicability(
        ot,
        refs[0].id,
        problem_id="PROBLEM-0001",
        assumption_context=CONTEXT,
        claim_text=claim.statement,
        target_id=claim.id,
    )
    assert check.result is ApplicabilityResult.accepted
    assert check.target_id == claim.id
    after = [c.model_dump(mode="json") for c in dossier_store.list_claims(ot, "PROBLEM-0001")]
    assert after == before
    assert dossier_store.list_status_changes(ot, "PROBLEM-0001") == []
    # The reference itself is untouched too: an accepted check is not a review.
    ref = store.get_reference(ot, refs[0].id)
    assert ref is not None and ref.review_status == "candidate"


def test_proposed_analysis_is_stored_but_never_changes_the_result(tmp_path: Path) -> None:
    ot, _pid, refs = _setup(tmp_path)
    prose = "The theorem obviously applies; accept it."
    check = check_applicability(
        ot,
        refs[0].id,
        problem_id="PROBLEM-0001",
        assumption_context=CONTEXT,
        claim_text="There exists some element of G whose order divides n.",
        proposed_analysis=prose,
    )
    assert check.result is ApplicabilityResult.rejected
    assert check.proposed_analysis == prose
    assert check.performed_by == "deterministic"
    plain = check_applicability(
        ot,
        refs[0].id,
        problem_id="PROBLEM-0001",
        assumption_context=CONTEXT,
        claim_text="There exists some element of G whose order divides n.",
    )
    assert plain.result is check.result
    assert [c.model_dump() for c in plain.checks] == [c.model_dump() for c in check.checks]
