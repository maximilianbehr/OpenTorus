"""Tests for the standalone HTML report and the design system it shares with the PDF."""

from __future__ import annotations

import re

from opentorus.research.dossier.html_export import markdown_to_html
from opentorus.research.dossier.pdf_export import opentorus_cls_source, status_chip
from opentorus.research.dossier.theme import PALETTE, report_css, status_kind


def test_palette_matches_the_latex_class() -> None:
    """theme.py and opentorus.cls must define the same colours.

    The LaTeX class cannot import Python, so the palette is written twice. This
    pins the two copies together — without it the PDF and the HTML would drift
    into different-looking documents one edit at a time.
    """
    cls = opentorus_cls_source().read_text(encoding="utf-8")
    defined = dict(re.findall(r"\\definecolor\{(\w+)\}\{HTML\}\{([0-9A-Fa-f]{6})\}", cls))
    assert defined, "no \\definecolor lines found in opentorus.cls"
    for name, value in PALETTE.items():
        assert name in defined, f"{name} missing from opentorus.cls"
        assert defined[name].upper() == value.lstrip("#").upper(), name
    assert set(defined) == set(PALETTE), "colour defined on only one side"


def test_status_colour_agrees_between_pdf_and_html() -> None:
    """One status vocabulary, one colour rule, both renderings."""
    assert status_kind("verified") == "ok"
    assert status_chip("verified") == "\\statusok{verified}"
    assert status_kind("open") == "warn"
    assert status_chip("open") == "\\statuswarn{open}"
    assert status_kind("refuted") == "bad"
    assert status_chip("refuted") == "\\statusbad{refuted}"
    # Colour must never upgrade a claim: unknown statuses stay neutral in both.
    assert status_kind("unverified") == "neutral"
    assert status_chip("unverified") == "\\statusbadge{unverified}"


def test_page_is_self_contained_apart_from_mathjax() -> None:
    """The report is a local file: the stylesheet must be inlined, not fetched."""
    page = markdown_to_html("# Title\n\nBody.\n")
    assert "<style>" in page
    assert "<link" not in page
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
    assert external == ["https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"], external


def test_metadata_panel_sits_under_the_title() -> None:
    page = markdown_to_html(
        "# PROBLEM-0001 — T\n\nIntro.\n",
        meta=[("Status", '<span class="chip chip-warn">open</span>')],
    )
    assert page.index("<h1>") < page.index('class="ot-panel"') < page.index("<p>Intro.")
    # The label is upper-cased by CSS, not baked into the markup.
    assert 'class="ot-meta-label">Status<' in page
    assert '<span class="chip chip-warn">open</span>' in page


def test_soft_wrapped_lines_join_into_one_paragraph() -> None:
    """Markdown wraps at the source margin; each line must not become its own <p>."""
    page = markdown_to_html(
        "For every square matrix $A$ and every\npolynomial $p$, the bound\nholds.\n"
    )
    assert page.count("<p>") == 1
    assert "and every polynomial $p$, the bound holds." in page


def test_numbered_steps_render_as_an_ordered_list() -> None:
    page = markdown_to_html("1. Sample rows.\n2. Apply the bound.\n3. Conclude.\n")
    assert "<ol>" in page and "</ol>" in page
    assert page.count("<li>") == 3


def test_multiline_display_math_stays_one_span() -> None:
    """Split across paragraphs, MathJax never matches the delimiters."""
    page = markdown_to_html(
        "Crouzeix's conjecture states that\n"
        "$$\n\\lVert p(A) \\rVert_2 \\le 2 M,\n$$\n"
        "for every $p$.\n"
    )
    block = re.search(r'<p class="ot-display">(.*?)</p>', page, re.DOTALL)
    assert block is not None, page
    assert block.group(1).count("$$") == 2
    assert "\\lVert p(A) \\rVert_2" in block.group(1)


def test_artifact_ids_and_gap_markers_are_marked_up() -> None:
    page = markdown_to_html("Refuted by PAPER-0001 per EXP-0012, leaving [GAP-2] open.\n")
    assert '<span class="artifact">PAPER-0001</span>' in page
    assert '<span class="artifact">EXP-0012</span>' in page
    assert '<span class="gapmarker">[GAP-2]</span>' in page
    # Two-letter prefixes are ids too (KR-* known results).
    assert '<span class="artifact">KR-0002</span>' in markdown_to_html("See KR-0002.\n")
    # "PAPER-*" is a glob in prose, not an artifact id.
    assert '<span class="artifact">' not in markdown_to_html("cite only parsed PAPER-* artifacts\n")


def test_status_line_becomes_a_chip() -> None:
    page = markdown_to_html("- **Status:** open — still open.\n")
    assert '<span class="chip chip-warn">open</span>' in page
    # An unrecognised status label stays neutral rather than looking settled.
    assert 'chip chip-neutral">HEURISTIC_ONLY' in markdown_to_html("- **Status:** HEURISTIC_ONLY\n")


def test_underscores_inside_identifiers_are_not_italics() -> None:
    page = markdown_to_html("The status HEURISTIC_ONLY came from experiment_proof checks.\n")
    assert "<em>" not in page
    assert "HEURISTIC_ONLY" in page
    page = markdown_to_html("_Evidence supports claims but does not verify them._\n")
    assert "<em>Evidence supports claims but does not verify them.</em>" in page


def test_math_spans_reach_mathjax_untouched() -> None:
    """An id-looking token inside a formula is notation, not an artifact."""
    page = markdown_to_html("The bound $A_{PAPER-0001}$ and the artifact PAPER-0002.\n")
    assert "$A_{PAPER-0001}$" in page
    assert '<span class="artifact">PAPER-0001</span>' not in page
    assert '<span class="artifact">PAPER-0002</span>' in page


def test_pipe_tables_render_as_tables() -> None:
    page = markdown_to_html(
        "| Claim | Status |\n|---|---|\n| CLAIM-0001 | supported |\n| CLAIM-0002 | refuted |\n"
    )
    assert "<table>" in page and "<thead>" in page
    assert page.count("<tr>") == 3  # header + two rows
    assert "<th>Claim</th>" in page


def test_css_defines_the_shared_components() -> None:
    css = report_css()
    for selector in (".artifact", ".gapmarker", ".chip", ".ot-panel", ".ot-caution", ".ot-display"):
        assert selector in css, selector
    # A chip class per status kind, so no kind falls back to unstyled text.
    for kind in ("ok", "warn", "bad", "neutral"):
        assert f".chip-{kind}" in css
