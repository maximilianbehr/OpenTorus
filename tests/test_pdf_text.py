"""Tests for PDF text / page rendering helpers."""

from __future__ import annotations

from opentorus.research.pdf_text import (
    book_page_batches,
    effective_trailing_skip,
    extraction_char_count,
    is_usable_extraction,
    tail_page_range,
)


def test_is_usable_extraction_rejects_empty_pages() -> None:
    assert not is_usable_extraction([""] * 100)
    assert not is_usable_extraction(["   \n"] * 50)


def test_is_usable_extraction_accepts_real_text() -> None:
    pages = ["Introduction\n\nPolytopes are cool."] * 5
    assert is_usable_extraction(pages)


def test_tail_page_range() -> None:
    # Long book: scaled skip is 50, so the last-60 window ends at 381-50=331.
    assert tail_page_range(381, 60) == (272, 331)
    # 100-page doc: trailing skip scales to 25 (not the old fixed 50), so the
    # last-20-content-page window is 56..75, ending at 100-25=75.
    assert tail_page_range(100, 20) == (56, 75)


def test_book_page_batches_covers_full_main_matter() -> None:
    batches = book_page_batches(381, batch_size=4, skip_trailing=50)
    assert batches[0] == (1, 4)
    assert batches[-1][1] == 331
    assert any(start <= 330 <= end for start, end in batches)


def test_book_page_batches_short_pdf_scans_almost_all_pages() -> None:
    """57-page preprints must not collapse to ~7 pages (old fixed skip=50 bug)."""
    batches = book_page_batches(57, batch_size=4)
    assert batches[0][0] == 1
    assert batches[-1][1] >= 52
    assert effective_trailing_skip(57) <= 5


def test_effective_trailing_skip_scales_with_length() -> None:
    assert effective_trailing_skip(57) == 2
    assert effective_trailing_skip(381) == 50


def test_book_page_batches_honors_explicit_range() -> None:
    batches = book_page_batches(381, batch_size=4, page_from=325, page_to=335)
    assert batches[0][0] == 325
    assert batches[-1][1] == 335


def test_extraction_char_count() -> None:
    assert extraction_char_count([" abc ", ""]) == 3
