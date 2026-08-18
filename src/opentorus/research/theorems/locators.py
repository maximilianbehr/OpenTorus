"""Locate and validate a theorem reference inside a locally parsed paper.

What can and cannot be checked follows from how papers are cached (see
``research/papers.py``): ``text.txt`` is the page-joined full text *without page
markers*, and ``structure.json`` is a section outline (title, first page, first
280 chars). Therefore:

* the ``label`` ("Theorem 2.1") is checked against the parsed corpus — this is the
  one locator component that can be confirmed or refuted;
* ``page`` is only checked to lie within ``num_pages`` when ``structure.json``
  exists; otherwise it is recorded as *unverifiable* (a warning, never invented);
* ``section`` is checked against the section titles in ``structure.json`` when
  present; otherwise it is unverifiable too.

``located_context`` and ``location_hash`` always work on the *full* corpus
(:func:`paper_citations.paper_corpus`) and prefer a hit inside the full body over
the truncated outline text, so the hash pins the statement as it appears in the
source, never a 280-char preview.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.research.paper_citations import (
    _RESULT_KW,
    _flex_number_pattern,
    available_theorem_numbers,
    corpus_has_numbered_theorems,
    paper_corpus,
    theorem_in_corpus,
)
from opentorus.research.reading import PaperStructure
from opentorus.research.theorems.models import EXCERPT_LIMIT, SourceLocator

# "Theorem 2.1", "lemma 3", "2.1" (bare number: any numbered environment).
_LABEL = re.compile(rf"^\s*(?:({_RESULT_KW})\s*)?(\d+(?:\.\d+)*)\s*\.?\s*$", re.I)
# A statement label is followed by ".", ":" or a parenthesised title; a citation in
# running text ("by Theorem 2.1 we get") is not.
_STATEMENT_TAIL = re.compile(r"\s*[.:(]")
# Where a statement ends: the next statement-like environment label, a "Proof."
# marker, a numbered heading on its own line, or the reading-note part of the
# corpus ("# PAPER-..."). Cutting there keeps one theorem's hypotheses from being
# attributed to its neighbour.
_STATEMENT_END = re.compile(
    rf"(?:\b{_RESULT_KW}\s*\d+(?:\s*\.\s*\d+)*\s*[.:(])"
    r"|(?:\bProof\b\s*[.:(])"
    r"|(?:\n\s*\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z]+[^\n]{0,60}\n)"
    r"|(?:\n#+\s+PAPER-\d{4})",
    re.I,
)


class LocatorValidation(BaseModel):
    """Outcome of :func:`validate_locator`: blocking errors vs. honest warnings."""

    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    context: str | None = None
    page_checked: bool = False
    section_checked: bool = False


def parse_label(label: str | None) -> tuple[str | None, str | None]:
    """Split a label into ``(keyword, number)``; keyword may be None for a bare number."""
    if not label:
        return None, None
    m = _LABEL.match(label)
    if m is None:
        return None, None
    keyword = m.group(1).lower() if m.group(1) else None
    return keyword, m.group(2)


def clip_excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    """Whitespace-normalise and clip to ``limit`` chars at a word boundary."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 3]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "..."


def location_hash(context: str) -> str:
    """sha256 over the whitespace-normalised located context."""
    flat = " ".join(context.split())
    return hashlib.sha256(flat.encode("utf-8")).hexdigest()


def label_pattern(keyword: str | None, number: str) -> re.Pattern[str]:
    """Regex for one label in a raw corpus, tolerant of extraction noise in the dot.

    The lookaheads keep ``2.1`` from matching the prefix of ``2.10`` or ``2.1.5``.
    """
    kw = re.escape(keyword) if keyword else _RESULT_KW
    return re.compile(
        rf"\b{kw}\s*{_flex_number_pattern(number)}(?!\d)(?!\s*\.\s*\d)",
        re.I,
    )


def _body_offset(ot_dir: Path, paper_id: str, corpus: str) -> int:
    """Offset of the full ``text.txt`` body inside the joined corpus (0 if unknown).

    ``paper_corpus`` prepends the structure outline (truncated section previews);
    a label found there has a cut-off context, so callers prefer hits at or after
    this offset.
    """
    from opentorus.research.papers import get_paper

    paper = get_paper(ot_dir, paper_id.upper())
    if paper is None or not paper.text_path:
        return 0
    path = ot_dir / paper.text_path
    if not path.is_file():
        return 0
    try:
        body = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return 0
    if not body:
        return 0
    idx = corpus.find(body)
    return idx if idx >= 0 else 0


def find_label(
    corpus: str, keyword: str | None, number: str, *, body_offset: int = 0
) -> re.Match[str] | None:
    """The occurrence of a label that best represents its *statement*.

    Preference order: an occurrence inside the full body (at/after ``body_offset``)
    over the outline preview; a statement-like occurrence (followed by ``.``, ``:``
    or ``(``) over a citation in running text; earlier over later. Extraction and
    re-location use this same rule, so a stored ``location_hash`` is reproducible.
    """
    matches = list(label_pattern(keyword, number).finditer(corpus))
    if not matches:
        return None
    in_body = [m for m in matches if m.start() >= body_offset] or matches
    statement_like = [m for m in in_body if _STATEMENT_TAIL.match(corpus, m.end())]
    return (statement_like or in_body)[0]


def context_at(corpus: str, start: int, *, width: int = 400) -> str:
    """The statement text at ``start``: at most ``width`` raw chars, cut at the next
    environment / proof marker / heading, whitespace-collapsed."""
    window = corpus[start : start + width]
    # Skip the label itself (it is statement-like by construction) before looking
    # for the *next* environment.
    m = _STATEMENT_END.search(window, 1)
    if m is not None:
        window = window[: m.start()]
    return " ".join(window.split()).strip()


def located_context(ot_dir: Path, locator: SourceLocator, *, width: int = 400) -> str | None:
    """The source text starting at the locator's label in the full parsed corpus.

    Returns ``None`` when the paper is unparsed, the label has no number, or the
    label does not occur in the corpus.
    """
    keyword, number = parse_label(locator.label)
    if number is None:
        return None
    corpus = paper_corpus(ot_dir, locator.paper_id, lower=False)
    if corpus is None:
        return None
    match = find_label(
        corpus, keyword, number, body_offset=_body_offset(ot_dir, locator.paper_id, corpus)
    )
    if match is None:
        return None
    return context_at(corpus, match.start(), width=width)


def load_structure(ot_dir: Path, paper_id: str) -> PaperStructure | None:
    """The persisted ``structure.json`` outline, or ``None`` when absent/unreadable."""
    from opentorus.research.papers import get_paper, papers_dir

    paper = get_paper(ot_dir, paper_id.upper())
    if paper is None:
        return None
    path = papers_dir(ot_dir) / paper.id / "structure.json"
    if not path.is_file():
        return None
    try:
        return PaperStructure.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def validate_locator(ot_dir: Path, locator: SourceLocator) -> LocatorValidation:
    """Check a locator against the local paper artifacts.

    Errors (``ok=False``): unknown paper; a numbered label the parsed corpus
    demonstrably lacks (the corpus *has* numbering); a page beyond ``num_pages``;
    a section title not in the outline. Everything the cache cannot decide is a
    warning: unparsed paper, corpus without extractable numbering, page/section
    with no ``structure.json`` to check against.
    """
    from opentorus.research.papers import get_paper

    errors: list[str] = []
    warnings: list[str] = []
    context: str | None = None
    page_checked = False
    section_checked = False

    paper_id = locator.paper_id.strip().upper()
    if get_paper(ot_dir, paper_id) is None:
        errors.append(f"unknown paper '{paper_id}': not a local artifact")
        return LocatorValidation(ok=False, errors=errors, warnings=warnings)

    corpus_lower = paper_corpus(ot_dir, paper_id)
    if corpus_lower is None:
        warnings.append(
            f"unparsed: {paper_id} has no parsed full text, so the label cannot be checked"
        )

    if locator.label:
        keyword, number = parse_label(locator.label)
        if number is None:
            warnings.append(f"label '{locator.label}' carries no result number; nothing to locate")
        elif corpus_lower is not None:
            if theorem_in_corpus(corpus_lower, number):
                context = located_context(ot_dir, locator)
                if context is None:
                    # The number exists under another keyword (e.g. Lemma 2.1 but the
                    # locator says Theorem 2.1) — verifiable, and wrong.
                    errors.append(
                        f"{paper_id} has a numbered result {number} but not as "
                        f"'{locator.label.strip()}'"
                    )
            elif corpus_has_numbered_theorems(corpus_lower):
                available = available_theorem_numbers(corpus_lower)
                shown = ", ".join(available[:12]) + (" ..." if len(available) > 12 else "")
                errors.append(
                    f"{paper_id} does not contain a numbered result {number}"
                    + (f" (parsed text contains: {shown})" if shown else "")
                )
            else:
                warnings.append(
                    f"{paper_id}: the parsed text has no extractable numbering, so "
                    f"'{locator.label.strip()}' can be neither confirmed nor refuted"
                )

    structure = load_structure(ot_dir, paper_id)
    if locator.page is not None:
        if structure is not None and structure.num_pages > 0:
            page_checked = True
            if locator.page < 1 or locator.page > structure.num_pages:
                errors.append(
                    f"page {locator.page} is outside {paper_id} "
                    f"(structure.json records {structure.num_pages} pages)"
                )
        else:
            warnings.append(
                f"page {locator.page} unverifiable: {paper_id} has no structure.json page count "
                "(the cached text carries no page markers)"
            )

    if locator.section:
        if structure is not None and structure.sections:
            section_checked = True
            wanted = locator.section.strip().casefold()
            titles = [s.title.strip() for s in structure.sections]
            hit = any(
                wanted == t.casefold() or wanted in t.casefold() or t.casefold() in wanted
                for t in titles
                if t
            )
            if not hit:
                shown = "; ".join(titles[:8]) + (" ..." if len(titles) > 8 else "")
                errors.append(
                    f"section '{locator.section.strip()}' not found in {paper_id} outline"
                    + (f" (sections: {shown})" if shown else "")
                )
        else:
            warnings.append(
                f"section '{locator.section.strip()}' unverifiable: {paper_id} has no "
                "structure.json outline"
            )

    return LocatorValidation(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        context=context,
        page_checked=page_checked,
        section_checked=section_checked,
    )
