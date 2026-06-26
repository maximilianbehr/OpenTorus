"""Tests for paper citation validation and literature-phase guards."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.literature_gate import literature_tool_gate
from opentorus.research.paper_citations import (
    available_theorem_numbers,
    corpus_has_numbered_theorems,
    theorem_in_corpus,
    validate_proof_citations,
)
from opentorus.research.papers import acquire_paper, read_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.workspace import init_workspace


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return tmp_path / ".opentorus"


def test_theorem_in_corpus() -> None:
    text = "We prove Theorem 3.1 on page 5. Lemma 2.4 follows."
    assert theorem_in_corpus(text, "3.1")
    assert theorem_in_corpus(text, "2.4")
    assert not theorem_in_corpus(text, "9.9")


def test_recognizes_all_numbered_environments() -> None:
    # Not just theorems/lemmas: a number that exists only as a Definition/Remark/
    # Corollary/Example/Equation must be recognized (the reported false rejection of
    # "Definition 1.1" when the paper had no Theorem 1.1).
    corpus = (
        "Definition 1.1 (sketch). Theorem 1.2 holds. Lemma 1.6. Corollary 2.1. "
        "Remark 4.10. Example 3.2. equation 5.1."
    )
    for n in ("1.1", "1.2", "1.6", "2.1", "4.10", "3.2", "5.1"):
        assert theorem_in_corpus(corpus, n), n
    assert not theorem_in_corpus(corpus, "9.9")
    assert available_theorem_numbers(corpus) == ["1.1", "1.2", "1.6", "2.1", "3.2", "4.10", "5.1"]
    assert corpus_has_numbered_theorems("Only a Definition 1.1 here.")


def test_definition_citation_is_not_rejected(tmp_path: Path) -> None:
    # PAPER-0001 has Definition 1.1 (not Theorem 1.1); citing it must be accepted.
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Tensor concentration", arxiv_id="2411.10633")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = [
        "1 Introduction\nDefinition 1.1 (injective norm). Theorem 1.2 follows. Lemma 1.6.\n",
    ]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "By Definition 1.1 of PAPER-0001 the injective norm is well defined."
    errors, _ = validate_proof_citations(ot, body)
    assert not errors  # Definition 1.1 exists → no fabricated-citation block


def test_full_body_results_survive_parsing_for_citation_grounding(tmp_path: Path) -> None:
    # Regression: ``structure.json`` keeps only a 280-char outline per section, so a
    # result deep in a section (e.g. ``Lemma 3.1`` after a long preamble) used to be
    # invisible to citation grounding and wrongly rejected as invented. read_paper now
    # also persists the full text, so the whole body is searchable.
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Tensor concentration", arxiv_id="2411.10633")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    filler = "We develop the estimate in detail. " * 40  # > 280 chars before the result
    pages = [
        "1 Introduction\nTheorem 1.2 holds.\n",
        f"3 Main results\n{filler}\nLemma 3.1 (key estimate). The bound follows.\n",
    ]
    paper = read_paper(ot, paper.id, page_extractor=lambda path: pages)

    assert paper.text_path and (ot / paper.text_path).is_file()
    body = "By Lemma 3.1 in PAPER-0001 the estimate holds."
    errors, _ = validate_proof_citations(ot, body)
    assert not errors  # Lemma 3.1 is deep in the body but still grounded


def test_validate_proof_citations_rejects_hallucinated_theorem(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Matrix bounds", arxiv_id="2401.00001")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = [
        "1 Introduction\nWe study matrix functions.\n",
        "2 Results\nTheorem 2.1. The Lanczos error decays exponentially.\n",
    ]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "By Theorem 3.1 in PAPER-0001, tensor networks converge for local Hamiltonians."
    errors, _ = validate_proof_citations(ot, body)
    assert errors
    assert any("3.1" in e for e in errors)


def test_validate_proof_citations_accepts_parsed_theorem(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Matrix bounds", arxiv_id="2401.00002")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = ["2 Results\nTheorem 2.1. The error bound holds on the interval.\n"]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "Apply Theorem 2.1 in PAPER-0001 to bound the sign-function error."
    errors, warnings = validate_proof_citations(ot, body)
    assert not errors
    # A valid parsed theorem citation is accepted, and now gets a non-blocking
    # source-context advisory so a reviewer can confirm the statement matches.
    assert any("source context" in w for w in warnings)


def test_theorem_in_corpus_tolerates_extraction_noise() -> None:
    # PDF extraction often drops the space ("Theorem2.1") or splits the dot ("1 . 3").
    assert theorem_in_corpus("see Theorem2.1 here", "2.1")
    assert theorem_in_corpus("see Theorem 1 . 3 here", "1.3")
    assert corpus_has_numbered_theorems("intro Theorem 4 results")
    assert not corpus_has_numbered_theorems("only prose, no numbered results here")


def test_missing_theorem_warns_when_extraction_has_no_numbering(tmp_path: Path) -> None:
    # The root cause of the random_nla stall: a paper whose extraction captured no
    # numbered theorems must NOT hard-block every citation as "invented" — the
    # grounding cannot verify it either way, so it warns instead.
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Survey", arxiv_id="2401.00003")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = ["Abstract\nThis survey discusses sketching and error estimation in prose only.\n"]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "By Theorem 4.2 of PAPER-0001 the adaptive sketch error is bounded."
    errors, warnings = validate_proof_citations(ot, body)
    assert not errors  # unverifiable, not invented → does not block proof writing
    assert any("cannot verify" in w and "4.2" in w for w in warnings)


def test_missing_theorem_blocks_when_paper_has_other_numbers(tmp_path: Path) -> None:
    # When the paper DOES have numbered results but not the cited one, it is a genuine
    # invention and is still blocked.
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Sparse JL", arxiv_id="2401.00004")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = ["Results\nTheorem 1 holds. Lemma 6 follows. Lemma 9 too.\n"]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "By Theorem 1.3 of PAPER-0001 the projection preserves norms."
    errors, _ = validate_proof_citations(ot, body)
    assert any("1.3" in e for e in errors)


def test_blocked_citation_lists_available_theorem_numbers(tmp_path: Path) -> None:
    # The rejection must tell the model which numbers the paper actually has, so it can
    # cite a real one instead of guessing (the loop that blocked proof writing).
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Sparse JL", arxiv_id="2401.00009")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = ["Results\nTheorem 1.3 holds. Lemma 2.1 follows. Theorem 4.2 too.\n"]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = "By Theorem 7.9 of PAPER-0001 the bound follows."
    errors, _ = validate_proof_citations(ot, body)
    assert errors
    err = " ".join(errors)
    assert "1.3" in err and "2.1" in err and "4.2" in err
    assert "[GAP-n]" in err


def test_available_theorem_numbers_sorted_numerically() -> None:
    from opentorus.research.paper_citations import available_theorem_numbers

    corpus = "theorem 10.1 ... lemma 2.1 ... theorem 1 ... proposition 2.10"
    assert available_theorem_numbers(corpus) == ["1", "2.1", "2.10", "10.1"]


def test_blocked_citation_suggests_the_right_result_by_content(tmp_path: Path) -> None:
    # Reproduces the PAPER-0001 livelock: the model cites a nonexistent number but its
    # prose describes a result that DOES exist under a different number. The rejection
    # must point at that result by content so the model stops guessing the number.
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Backward error", arxiv_id="2401.00021")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    pages = [
        "Results\n"
        "Theorem 3.3 (Richardson iteration). After k steps of Richardson iteration on a "
        "PSD linear system, the backward error decays at a universal convergence rate.\n"
        "Theorem 5.1. For general systems the rate depends logarithmically on the "
        "condition number.\n"
    ]
    read_paper(ot, paper.id, page_extractor=lambda path: pages)

    body = (
        "By Theorem 1.2 of PAPER-0001, Richardson iteration on a PSD system achieves a "
        "universal convergence rate independent of the condition number."
    )
    errors, _ = validate_proof_citations(ot, body)
    assert errors
    err = " ".join(errors)
    # Still rejects the invented number...
    assert "1.2" in err
    # ...but now names the real result the prose described, with a snippet of its statement.
    assert "3.3" in err
    assert "Closest match" in err and "Richardson" in err


def test_content_suggestion_ranks_by_overlap(tmp_path: Path) -> None:
    from opentorus.research.paper_citations import suggest_results_by_content

    corpus = (
        "Theorem 3.3 (Richardson iteration). Universal convergence on PSD systems.\n"
        "Theorem 9.9 (unrelated). A statement about random graphs and colorings.\n"
    )
    query = "Richardson iteration gives universal convergence on PSD systems"
    suggestions = suggest_results_by_content(corpus, query, ["3.3", "9.9"])
    assert suggestions and suggestions[0][0] == "3.3"


def test_literature_tool_gate_blocks_proof_write() -> None:
    gate = literature_tool_gate()
    msg = gate("proof_write", {"problem_id": "PROBLEM-0001", "title": "x"})
    assert msg is not None
    assert "literature phase" in msg.lower()


def test_literature_tool_gate_requires_paper_id_in_observation() -> None:
    gate = literature_tool_gate(phase_complete=lambda: False)
    blocked = gate("memory_add", {"text": "No paper id here", "kind": "observations"})
    assert blocked is not None
    ok = gate(
        "memory_add",
        {"text": "PAPER-0001 Theorem 2.1: error bound on [-1,1].", "kind": "observations"},
    )
    assert ok is None
