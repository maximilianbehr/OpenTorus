"""Tests for structured extraction and reading notes (Milestone 45).

Parsing operates on already-extracted page text, so a small fixture stands in
for a real PDF (no ``pypdf`` needed). We verify sections + references parse, the
note schema is populated, and stated limitations are captured.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.papers import (
    acquire_paper,
    is_paper_parsed,
    read_paper,
    reading_note_excerpt,
)
from opentorus.research.reading import (
    build_paper_note,
    parse_structure,
    render_note_markdown,
)
from opentorus.research.sources.base import SourceRecord
from opentorus.workspace import init_workspace

FIXTURE_PAGES = [
    # page 1
    "Abstract\n"
    "We present a fast solver for toric eigenvalue problems. "
    "Our main contribution is a new preconditioner.\n"
    "1 Introduction\n"
    "Eigenvalue problems are central. We assume the matrix is Hermitian.\n",
    # page 2
    "2 Method\n"
    "We derive the preconditioner from a low-rank update. "
    "We suppose the spectrum is clustered.\n"
    "3 Experiments\n"
    "We evaluate on the SuiteSparse dataset and the synthetic benchmark.\n"
    "4 Results\n"
    "Our method converges 3x faster than the baseline.\n",
    # page 3
    "5 Limitations\n"
    "The approach cannot handle non-normal matrices and however assumes clustering.\n"
    "References\n"
    "[1] A. Author. A prior method. Journal, 2019.\n"
    "[2] B. Researcher. Another method. Conf, 2020.\n",
]


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return tmp_path / ".opentorus"


def test_parse_structure_sections_and_references() -> None:
    structure = parse_structure(FIXTURE_PAGES)
    titles = [s.title for s in structure.sections]
    assert "Abstract" in titles
    assert "Method" in titles
    assert "Limitations" in titles
    assert structure.abstract and "fast solver" in structure.abstract
    assert structure.num_pages == 3
    assert len(structure.references) == 2
    assert structure.references[0].startswith("A. Author")


def test_section_page_provenance() -> None:
    structure = parse_structure(FIXTURE_PAGES)
    method = next(s for s in structure.sections if s.title == "Method")
    limitations = next(s for s in structure.sections if s.title == "Limitations")
    assert method.page == 2
    assert limitations.page == 3


def test_build_note_populates_schema() -> None:
    structure = parse_structure(FIXTURE_PAGES)
    note = build_paper_note("PAPER-0001", structure, title="Toric Solver")
    assert "preconditioner" in note.contribution
    assert "low-rank" in note.method
    assert "faster" in note.key_results
    assert any("clustered" in a or "Hermitian" in a for a in note.assumptions)
    assert any("SuiteSparse" in d or "benchmark" in d for d in note.datasets)
    assert any("non-normal" in lim for lim in note.stated_limitations)
    assert note.provenance.get("method") == [2]


def test_render_note_markdown_has_sections() -> None:
    structure = parse_structure(FIXTURE_PAGES)
    note = build_paper_note("PAPER-0001", structure, title="T")
    md = render_note_markdown(note)
    assert "## Contribution" in md
    assert "## Stated limitations" in md
    assert "evidence" in md.lower()


def test_build_note_falls_back_to_theorem_mentions() -> None:
    pages = [
        "1 Introduction\nWe study approximation.\n",
        "2 Main results\n"
        "Theorem 4.2. The minimax error En(f) decays like n^{-alpha} on [-1,1].\n"
        "Lemma 4.3. A corollary for sign-like functions.\n",
        "References\n[1] Author. Paper. 2020.\n",
    ]
    structure = parse_structure(pages)
    note = build_paper_note("PAPER-0002", structure, title="Approx")
    assert "Theorem 4.2" in note.key_results
    assert "Lemma 4.3" in note.key_results


def test_read_paper_writes_artifacts(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Toric Solver", arxiv_id="2401.00002")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF fake")
    read = read_paper(ot, paper.id, page_extractor=lambda path: FIXTURE_PAGES)
    assert read.note_path and (ot / read.note_path).is_file()
    assert read.structure_path and (ot / read.structure_path).is_file()
    note_md = (ot / read.note_path).read_text()
    assert "## Method" in note_md


def test_read_paper_requires_local_full_text(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="ieee", title="Locked", doi="10.9/x", is_open_access=False)
    paper = acquire_paper(
        ot, record, contact_email="me@uni.edu", unpaywall=lambda d, e: (None, None)
    )
    try:
        read_paper(ot, paper.id, page_extractor=lambda path: FIXTURE_PAGES)
        raise AssertionError("expected an error for a paper without local full text")
    except Exception as exc:  # noqa: BLE001
        assert "no local full text" in str(exc)


def test_is_paper_parsed_and_reading_excerpt(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    record = SourceRecord(source="arxiv", title="Toric Solver", arxiv_id="2401.00003")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF fake")
    assert is_paper_parsed(ot, paper) is False
    assert "PLACEHOLDER ONLY" in reading_note_excerpt(ot, paper)
    read = read_paper(ot, paper.id, page_extractor=lambda path: FIXTURE_PAGES)
    assert is_paper_parsed(ot, read) is True
    excerpt = reading_note_excerpt(ot, read)
    assert "## Contribution" in excerpt
    assert "preconditioner" in excerpt
