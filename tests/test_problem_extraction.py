"""Tests for problem extraction into PROBLEM-* dossiers (open questions extracted from papers)."""

from __future__ import annotations

from pathlib import Path

import yaml

from opentorus.agent.session import SessionMessage
from opentorus.providers._convert import to_ollama_messages
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.dossier.store import list_dossiers, read_statement
from opentorus.research.papers import add_paper, get_paper, papers_dir
from opentorus.research.problem_extraction import (
    _heuristic_extract,
    _llm_extract,
    _register_one,
    _vision_extract_batch,
    _vision_extract_book,
    dossier_label_from_tags,
    extract_labeled_problem_block,
    extract_markdown_workshop_problems,
    extract_problems_from_markdown,
    extract_problems_from_paper,
    refresh_dossier_statement_from_source,
)
from opentorus.workspace import init_workspace, workspace_dir


def _dossier_label(d) -> str:
    return dossier_label_from_tags(d.tags) or ""


def _dossier_statement(base: Path, d) -> str:
    return read_statement(base, d.id)


def _dossiers_for_paper(base: Path, paper_id: str):
    return [d for d in list_dossiers(base) if paper_id in d.tags]


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _attach_note(base: Path, paper_id: str, body: str) -> None:
    note_file = base / "summaries" / f"{paper_id}.md"
    note_file.parent.mkdir(parents=True, exist_ok=True)
    note_file.write_text(body, encoding="utf-8")
    paper = get_paper(base, paper_id)
    assert paper is not None
    paper.note_path = str(note_file.relative_to(base))
    paper.summary_path = paper.note_path
    meta = papers_dir(base) / paper_id / "metadata.yaml"
    meta.write_text(
        yaml.safe_dump(paper.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )


def _attach_text(base: Path, paper_id: str, body: str) -> None:
    text_file = papers_dir(base) / paper_id / "text.txt"
    text_file.parent.mkdir(parents=True, exist_ok=True)
    text_file.write_text(body, encoding="utf-8")
    paper = get_paper(base, paper_id)
    assert paper is not None
    paper.text_path = str(text_file.relative_to(base))
    meta = papers_dir(base) / paper_id / "metadata.yaml"
    meta.write_text(
        yaml.safe_dump(paper.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )


class _FakeProvider(BaseProvider):
    name = "fake"

    def __init__(self, content: str) -> None:
        self._content = content

    def generate(
        self,
        messages: list[SessionMessage],
        tools: list[dict] | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(kind="message", content=self._content)


def test_extract_questions_from_note_text(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/workshop.pdf")
    _attach_note(
        base,
        paper.id,
        "# Open problems\n\n"
        "Problem 3.1. Is the Crouzeix ratio bounded by 2 for all n×n matrices?\n\n"
        "Open Question 4.2: Find a counterexample for n=5.\n",
    )

    outcome = extract_problems_from_paper(base, paper.id, use_llm=False)
    assert len(outcome.problems) >= 2
    assert outcome.method == "heuristic"
    assert all(paper.id in q.tags for q in outcome.problems)
    assert all(q.id.startswith("PROBLEM-") for q in outcome.problems)
    assert list_dossiers(base)


def test_prefer_llm_skips_text_block_shortcut(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/workshop.pdf")
    # Paper text has a clean "Problem 3.1" block the heuristic would normally grab.
    _attach_text(
        base,
        paper.id,
        "Problem 3.1. Is the Crouzeix ratio bounded by 2 for all n×n matrices?\n",
    )
    llm_payload = (
        '[{"label": "3.1", "statement": "LLM-rewritten: bound the Crouzeix ratio.", '
        '"section": "Open problems"}]'
    )
    outcome = extract_problems_from_paper(
        base,
        paper.id,
        provider=_FakeProvider(llm_payload),
        use_llm=True,
        prefer_llm=True,
    )
    # method == "llm" proves the text-block shortcut was skipped and the LLM drove
    # extraction. (The stored statement is still enriched from the verbatim paper
    # block, which is intended for faithfulness.)
    assert outcome.method == "llm"
    assert any(_dossier_label(q) == "3.1" for q in outcome.problems)


def test_force_vision_skips_text_layer_shortcut(tmp_path: Path, monkeypatch) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/workshop.pdf")
    _attach_text(
        base,
        paper.id,
        "Problem 3.1. Is the Crouzeix ratio bounded by 2 for all n×n matrices?\n",
    )
    # Give the paper a local PDF path and stub the PDF/vision machinery.
    pdf = base / "papers" / paper.id / "paper.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 stub")
    p = get_paper(base, paper.id)
    assert p is not None
    p.local_path = str(pdf.relative_to(base))
    from opentorus.research.papers import papers_dir

    meta = papers_dir(base) / paper.id / "metadata.yaml"
    meta.write_text(yaml.safe_dump(p.model_dump(mode="json"), sort_keys=False), encoding="utf-8")

    import opentorus.research.pdf_text as pdf_text
    import opentorus.research.problem_extraction as oq

    monkeypatch.setattr(pdf_text, "pdftoppm_available", lambda: True)
    monkeypatch.setattr(pdf_text, "pdf_page_count", lambda _p: 2)
    monkeypatch.setattr(pdf_text, "book_page_batches", lambda *a, **k: [(1, 2)])
    # Text layer IS usable, so only force_vision should route us into vision.
    monkeypatch.setattr(pdf_text, "extract_pdf_pages_pypdf", lambda _p: ["full text layer"] * 5)
    monkeypatch.setattr(pdf_text, "is_usable_extraction", lambda _pages: True)

    called = {"vision": False}

    def _fake_vision_book(*_args, **_kwargs):
        called["vision"] = True
        return oq._register_candidates(
            base,
            [("3.1", "Vision-read: bound the Crouzeix ratio for all matrices.", "Open problems")],
            paper_id=paper.id,
        )

    monkeypatch.setattr(oq, "_vision_extract_book", _fake_vision_book)
    monkeypatch.setattr(
        "opentorus.providers.vision.require_vision_provider",
        lambda *args, **kwargs: None,
    )

    outcome = oq.extract_problems_from_paper(
        base,
        paper.id,
        provider=_FakeProvider("[]"),
        use_llm=True,
        force_vision=True,
    )
    assert called["vision"] is True
    assert outcome.method == "vision"


def test_prefer_llm_without_provider_falls_back_to_heuristic(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/workshop.pdf")
    _attach_text(
        base,
        paper.id,
        "Problem 3.1. Is the Crouzeix ratio bounded by 2 for all n×n matrices?\n",
    )
    # prefer_llm is requested but no usable provider → heuristic path still runs.
    outcome = extract_problems_from_paper(base, paper.id, use_llm=True, prefer_llm=True)
    assert outcome.method == "heuristic"
    assert len(outcome.problems) >= 1


def test_extract_skips_duplicates(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/x.pdf")
    _attach_note(
        base,
        paper.id,
        "Problem 1.1. Same statement repeated here for testing purposes.\n",
    )
    first = extract_problems_from_paper(base, paper.id, use_llm=False)
    second = extract_problems_from_paper(base, paper.id, use_llm=False)
    assert len(first.problems) == 1
    assert len(second.problems) == 1
    assert first.problems[0].id == second.problems[0].id


def test_extract_from_open_problems_section_with_bare_numbers(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/book.pdf")
    _attach_text(
        base,
        paper.id,
        "Appendix A\n\n"
        "Open Problems\n\n"
        "1. Does every 3-polytope with n vertices have at most 2n-5 edges in the graph?\n"
        "2. Characterize the f-vectors of 4-polytopes with simplicial facets.\n"
        "3. Is the diameter of the graph of a simple polytope bounded by a polynomial in n?\n",
    )

    outcome = extract_problems_from_paper(base, paper.id, use_llm=False)
    assert len(outcome.problems) == 3
    labels = {_dossier_label(q) for q in outcome.problems}
    assert labels == {"1", "2", "3"}


def test_extract_research_problem_and_multiline(tmp_path: Path) -> None:
    text = (
        "Research Problems\n\n"
        "Open Problem 1. Find a combinatorial proof that\n"
        "the Euler characteristic equals the alternating sum of face counts.\n\n"
        "Problem 2. Prove or disprove the generalized lower bound theorem.\n"
    )
    found = _heuristic_extract(text)
    assert len(found) >= 2
    assert found[0][1].startswith("Find a combinatorial proof")
    assert "alternating sum" in found[0][1]


def test_heuristic_ignores_prose_starting_with_problem_or_question(tmp_path: Path) -> None:
    # Prose like "Questions that…", "Problem of…", "Problem for…" must NOT be parsed
    # as problem headers with single-letter labels ("s", "o", "f").
    text = (
        "Problem 2.1. Develop benchmark parameterized linear systems.\n\n"
        "Questions that form the basis of widely used methods in quantum chemistry remain.\n"
        "The problem of derandomizing this approach is also of interest.\n"
        "Problem for eigenvector-dependent nonlinear eigenvalue problems persists.\n"
    )
    found = _heuristic_extract(text)
    labels = {label for label, _, _ in found}
    assert labels == {"2.1"}
    assert "s" not in labels
    assert "o" not in labels
    assert "f" not in labels


def test_heuristic_accepts_alphanumeric_label_with_digit(tmp_path: Path) -> None:
    text = "Problem A1. Show that the construction generalizes to higher dimensions.\n"
    found = _heuristic_extract(text)
    assert any(label == "A1" for label, _, _ in found)


def test_reading_note_alone_misses_appendix_but_full_text_wins(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/polytopes.pdf")
    _attach_note(
        base,
        paper.id,
        "# PAPER-0001 — Lectures on Polytopes\n\n"
        "## Contribution\n\n(intro only — no open problems here)\n",
    )
    _attach_text(
        base,
        paper.id,
        "Open Problems\n\n"
        "Problem 1. Determine the maximum number of faces of a centrally symmetric polytope.\n",
    )

    outcome = extract_problems_from_paper(base, paper.id, use_llm=False)
    assert len(outcome.problems) == 1
    assert "centrally symmetric" in _dossier_statement(base, outcome.problems[0])


def test_llm_extract_prefers_model_when_available(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/book.pdf")
    _attach_text(
        base,
        paper.id,
        "Some appendix with awkward layout and no clear Problem labels.\n"
        "Still, the author asks whether every lattice polytope has a unimodular triangulation.\n",
    )
    provider = _FakeProvider(
        '[{"label": "A", '
        '"statement": "Does every lattice polytope admit a unimodular triangulation?", '
        '"section": "Appendix"}]'
    )

    outcome = extract_problems_from_paper(base, paper.id, provider=provider)
    assert outcome.method == "llm"
    assert len(outcome.problems) == 1
    assert "unimodular" in _dossier_statement(base, outcome.problems[0])


def test_llm_extract_parses_json_response(tmp_path: Path) -> None:
    provider = _FakeProvider(
        'Here are the problems:\n[{"label": "7", '
        '"statement": "Is the Hirsch conjecture true in dimension 4?", '
        '"section": "Open Problems"}]\n'
    )
    found = _llm_extract(
        "Open Problems\n\n7) Is the Hirsch conjecture true in dimension 4?",
        provider,
        paper_id="PAPER-0001",
        title="Polytopes",
    )
    assert len(found) == 1
    assert found[0][0] == "7"
    assert "Hirsch" in found[0][1]


def test_ollama_messages_include_images() -> None:
    msg = SessionMessage(role="user", content="read pages", images=["abc123"])
    payload = to_ollama_messages([msg])[0]
    assert payload["images"] == ["abc123"]


def test_vision_extract_batch_sends_images_to_provider(tmp_path: Path, monkeypatch) -> None:
    captured: list[SessionMessage] = []

    class _CapturingProvider(BaseProvider):
        name = "fake"

        def generate(
            self,
            messages: list[SessionMessage],
            tools: list[dict] | None = None,
        ) -> ProviderResponse:
            captured.extend(messages)
            return ProviderResponse(
                kind="message",
                content='[{"label": "1", "statement": "Is every simple polytope 2-linear?", '
                '"section": "Open Problems"}]',
            )

    monkeypatch.setattr(
        "opentorus.research.pdf_text.render_pdf_pages_base64",
        lambda *args, **kwargs: [(322, "pngbase64")],
    )

    provider = _CapturingProvider()
    found = _vision_extract_batch(
        provider,
        tmp_path / "dummy.pdf",
        paper_id="PAPER-0001",
        title="Lectures on Polytopes",
        page_from=322,
        page_to=325,
    )
    assert len(found) == 1
    assert captured[0].images == ["pngbase64"]


def test_vision_extract_book_reports_progress(tmp_path: Path, monkeypatch) -> None:
    lines: list[str] = []

    class _BatchProvider(BaseProvider):
        name = "fake"

        def generate(
            self,
            messages: list[SessionMessage],
            tools: list[dict] | None = None,
        ) -> ProviderResponse:
            return ProviderResponse(kind="message", content="[]")

    monkeypatch.setattr(
        "opentorus.research.problem_extraction._vision_extract_batch",
        lambda *args, **kwargs: [],
    )

    _vision_extract_book(
        _BatchProvider(),
        tmp_path / "dummy.pdf",
        [(1, 4), (5, 8)],
        ot_dir=_ws(tmp_path),
        paper_id="PAPER-0001",
        title="Book",
        total_pages=10,
        on_progress=lines.append,
    )
    assert any("[1/2]" in line for line in lines)
    assert any("[2/2]" in line for line in lines)


def test_scanned_pdf_uses_vision_path(tmp_path: Path, monkeypatch) -> None:
    base = _ws(tmp_path)
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    paper = add_paper(base, str(pdf))
    _attach_text(base, paper.id, "\n" * 200)

    monkeypatch.setattr(
        "opentorus.research.pdf_text.extract_pdf_pages_pypdf",
        lambda path: [""] * 381,
    )
    monkeypatch.setattr(
        "opentorus.research.pdf_text.pdf_page_count",
        lambda path: 381,
    )
    monkeypatch.setattr(
        "opentorus.research.pdf_text.pdftoppm_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "opentorus.research.problem_extraction._ensure_full_text",
        lambda *args: None,
    )
    monkeypatch.setattr(
        "opentorus.research.problem_extraction._vision_extract_batch",
        lambda *args, **kwargs: [
            ("1", "Does every 3-polytope have a vertex of degree 3?", "Open Problems"),
        ],
    )
    monkeypatch.setattr(
        "opentorus.providers.vision.require_vision_provider",
        lambda *args, **kwargs: None,
    )

    outcome = extract_problems_from_paper(
        base,
        paper.id,
        provider=_FakeProvider("[]"),
    )
    assert outcome.method == "vision"
    assert len(outcome.problems) == 1
    assert _dossiers_for_paper(base, paper.id)


def test_register_one_allows_same_label_different_statements(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/book.pdf")
    seen: set[str] = set()
    first = _register_one(
        base,
        "1",
        "First problem statement here for testing.",
        None,
        paper_id=paper.id,
        seen=seen,
    )
    second = _register_one(
        base,
        "1",
        "Second problem statement here for testing.",
        None,
        paper_id=paper.id,
        seen=seen,
    )
    assert first is not None
    assert second is not None
    assert first.id != second.id
    assert len(_dossiers_for_paper(base, paper.id)) == 2


def test_vision_extract_persists_before_completion(tmp_path: Path, monkeypatch) -> None:
    base = _ws(tmp_path)
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    paper = add_paper(base, str(pdf))

    monkeypatch.setattr(
        "opentorus.research.problem_extraction._vision_extract_batch",
        lambda *args, **kwargs: [
            ("9.16", "Is the Crouzeix ratio bounded by 2?", "Section 9"),
        ],
    )

    class _Provider(BaseProvider):
        name = "fake"

        def generate(
            self,
            messages: list[SessionMessage],
            tools: list[dict] | None = None,
        ) -> ProviderResponse:
            return ProviderResponse(kind="message", content="[]")

    saved = _vision_extract_book(
        _Provider(),
        pdf,
        [(1, 4)],
        ot_dir=base,
        paper_id=paper.id,
        title="Book",
        total_pages=10,
    )
    assert len(saved) == 1
    assert _dossiers_for_paper(base, paper.id)


def test_extract_labeled_problem_block() -> None:
    text = (
        "Section intro.\n"
        "Problem 5.1(Sketch-and-solve).Let A be full rank.\n"
        "Prove or disprove the bound.\n"
        "Likewise, one can ask for SVD:\n"
        "Problem 5.2(SVD).Let A be any matrix.\n"
    )
    block = extract_labeled_problem_block(text, "5.1")
    assert block is not None
    assert "Sketch-and-solve" in block
    assert "Prove or disprove the bound." in block
    assert "Problem 5.2" not in block


def test_refresh_statement_from_paper(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/workshop.pdf")
    _attach_text(
        base,
        paper.id,
        "Problem 5.1(Sketch-and-solve).Let A be full rank with many details.\n"
        "Prove or disprove the relative-error bound for least squares.",
    )
    seen: set[str] = set()
    dossier = _register_one(
        base,
        "5.1",
        "Short summary only.",
        None,
        paper_id=paper.id,
        seen=seen,
    )
    assert dossier is not None
    statement = refresh_dossier_statement_from_source(base, dossier.id)
    assert len(statement) > len("Short summary only.")
    assert "relative-error bound" in statement


def test_extract_prefers_full_problem_blocks(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    paper = add_paper(base, "https://example.com/workshop.pdf")
    _attach_text(
        base,
        paper.id,
        "5 Sketching\n"
        "Problem 5.1(Sketch-and-solve).Let A be a full-rank matrix and B a matrix.\n"
        "Let Omega be an oblivious subspace injection with injectivity 1-epsilon.\n"
        "Let Xtilde be the sketch-and-solve approximation (Moore-Penrose pseudoinverse).\n"
        "Prove or disprove the relative Frobenius error bound.\n"
        "Likewise for SVD:\n"
        "Problem 5.2(SVD).Let A be any matrix.\n",
    )
    provider = _FakeProvider(
        '[{"label": "5.1", "statement": "Short LLM summary.", "section": null}]'
    )

    outcome = extract_problems_from_paper(base, paper.id, provider=provider)
    assert outcome.method == "heuristic"
    assert len(outcome.problems) == 2
    by_label = {_dossier_label(q): q for q in outcome.problems}
    assert "Moore-Penrose" in _dossier_statement(base, by_label["5.1"])
    assert "Short LLM summary" not in _dossier_statement(base, by_label["5.1"])


def test_extract_problems_from_markdown_via_llm(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    md = tmp_path / "workshop.md"
    md.write_text(
        "# Open problems\n\n"
        "5.1. Prove the sketch-and-solve relative error bound for full-rank A.\n",
        encoding="utf-8",
    )
    provider = _FakeProvider(
        '[{"label": "5.1", "statement": "Bound the sketch-and-solve error.", '
        '"section": "Open problems"}]'
    )
    outcome = extract_problems_from_markdown(base, md, provider=provider)
    assert outcome.method == "llm"
    assert len(outcome.problems) == 1
    assert outcome.problems[0].id.startswith("PROBLEM-")


_FORNACE_NOTES = """\
## 4.1.5 Inverses of Laplacians and related matrices

A new motivation for column subset selection comes from Markov chain compression.
One is presented with a graph Laplacian L and wants a reduced model.

In it is proved that the nuclear Nyström error for inverse Laplacians
is a submodular function in I if one excludes the empty set.

This question may be extended to positive-definite SDD or SDDM matrices.

### Problem

**Prove or disprove the submodularity of the nuclear Nyström error when L is assumed to be**

1. **SDDM and positive-definite**, or
2. **SDD and positive-definite**.
"""


def test_extract_markdown_workshop_problem_section(tmp_path: Path) -> None:
    found = extract_markdown_workshop_problems(_FORNACE_NOTES)
    assert len(found) == 1
    label, body, section = found[0]
    assert label == "4.1.5"
    assert "submodular" in body.lower()
    assert "SDDM" in body
    assert "SDD and positive-definite" in body


def test_heuristic_skips_markdown_problem_numbered_alternatives() -> None:
    found = _heuristic_extract(_FORNACE_NOTES)
    assert found == []


def test_extract_markdown_prefers_full_block_over_llm_summary(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    md = tmp_path / "notes.md"
    md.write_text(_FORNACE_NOTES, encoding="utf-8")
    provider = _FakeProvider(
        '[{"label": "4.1.5", "statement": "Short LLM summary.", '
        '"section": "Inverses of Laplacians"}]'
    )
    outcome = extract_problems_from_markdown(base, md, provider=provider)
    assert len(outcome.problems) == 1
    statement = _dossier_statement(base, outcome.problems[0])
    assert "submodular" in statement.lower()
    assert "SDDM" in statement
    assert "Short LLM summary" not in statement


def test_extract_markdown_freeform_notes_via_llm(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    md = tmp_path / "notes.md"
    md.write_text(
        "## Matrix sign function\n\n"
        "Let $\\Pi_{2^m}^*$ be polynomials computable with $m$ matmuls.\n\n"
        "What is the asymptotic error $\\varepsilon_m^*$ as a function of $m$ and $\\delta$?\n",
        encoding="utf-8",
    )
    provider = _FakeProvider(
        '[{"label": "1", "statement": "What is the asymptotic error '
        '\\\\varepsilon_m^* as a function of m and delta?", "section": "Matrix sign function"}]'
    )
    outcome = extract_problems_from_markdown(base, md, provider=provider)
    assert outcome.method == "llm"
    assert len(outcome.problems) == 1


def test_extract_markdown_requires_provider(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    md = tmp_path / "notes.md"
    md.write_text("## Problem\n\nWhat is the answer?\n", encoding="utf-8")
    import pytest

    from opentorus.errors import OpenTorusError

    with pytest.raises(OpenTorusError, match="requires a configured model provider"):
        extract_problems_from_markdown(base, md, provider=None)


def test_heuristic_extract_survives_bare_heading() -> None:
    # A bare ``#`` heading before any titled section must not crash extraction.
    out = _heuristic_extract("#\n\nProblem 1. Prove that X holds for all n.")
    assert any(label == "1" for label, _body, _section in out)
    # A bare heading amid prose must also not crash (returns a list, possibly empty).
    assert isinstance(_heuristic_extract("intro\n\n#\n\nbody text"), list)
