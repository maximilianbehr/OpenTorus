"""Structured paper extraction and disciplined reading notes (Milestone 45).

A PDF is turned into inspectable *structure* (abstract, sections with page
provenance, reference list) and a fixed-schema *reading note* that separates what
the authors **claim** from what is **demonstrated**. Parsing is heuristic and
pure (operates on already-extracted page text), so it is fully testable without a
real PDF. Reading a paper is summarization, not endorsement — the note is
evidence, never a verified claim.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from opentorus.research.egress import redact

# Canonical section keywords used to detect headings and to route section text
# into the note schema.
_KEYWORDS = (
    "abstract",
    "introduction",
    "background",
    "related work",
    "preliminaries",
    "method",
    "methods",
    "methodology",
    "approach",
    "model",
    "theory",
    "experiments",
    "experimental setup",
    "results",
    "evaluation",
    "analysis",
    "discussion",
    "limitations",
    "threats to validity",
    "conclusion",
    "conclusions",
    "future work",
    "references",
    "bibliography",
    "acknowledgments",
    "acknowledgements",
    "appendix",
)

# "1 Introduction", "2.1 Our Method", "3. Results"
_NUM_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+([A-Z][A-Za-z0-9 \-/:]{2,60})\s*$")
_REF_MARKER = re.compile(r"^\s*(\[\d+\]|\d+\.)\s+")
_THEOREM_LINE = re.compile(
    r"\b(Theorem|Lemma|Proposition|Corollary)\s+(\d+(?:\.\d+)*)",
    re.I,
)


class PaperSection(BaseModel):
    title: str
    page: int
    text: str = ""


class PaperStructure(BaseModel):
    abstract: str | None = None
    sections: list[PaperSection] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    num_pages: int = 0


class PaperNote(BaseModel):
    """A fixed-schema reading note; every field is extracted evidence, not truth."""

    paper_id: str
    title: str | None = None
    contribution: str = ""
    method: str = ""
    assumptions: list[str] = Field(default_factory=list)
    key_results: str = ""
    datasets: list[str] = Field(default_factory=list)
    stated_limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, list[int]] = Field(default_factory=dict)


def _normalize_heading(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or len(stripped) > 70:
        return None
    match = _NUM_HEADING.match(stripped)
    if match:
        return match.group(2).strip()
    bare = stripped.rstrip(".: ").lower()
    if bare in _KEYWORDS:
        return stripped.rstrip(".: ")
    return None


def _is_references_title(title: str) -> bool:
    return title.strip().lower() in {"references", "bibliography"}


def parse_structure(pages: list[str]) -> PaperStructure:
    """Parse already-extracted page text into a :class:`PaperStructure`.

    Headings are detected by numbered patterns or canonical section keywords;
    text accrues to the current section with the page it started on. The
    reference list is captured separately so citations can be linked later.
    """
    structure = PaperStructure(num_pages=len(pages))
    current: PaperSection | None = None
    in_references = False
    ref_buffer: list[str] = []

    for page_no, page in enumerate(pages, start=1):
        for raw in page.splitlines():
            heading = _normalize_heading(raw)
            if heading is not None:
                if in_references and ref_buffer:
                    structure.references.extend(_split_references(ref_buffer))
                    ref_buffer = []
                current = PaperSection(title=heading, page=page_no)
                structure.sections.append(current)
                in_references = _is_references_title(heading)
                continue
            if in_references:
                if raw.strip():
                    ref_buffer.append(raw.strip())
                continue
            if current is not None and raw.strip():
                current.text = (current.text + " " + raw.strip()).strip()

    if ref_buffer:
        structure.references.extend(_split_references(ref_buffer))

    abstract = next(
        (s.text for s in structure.sections if s.title.strip().lower() == "abstract"), None
    )
    structure.abstract = abstract
    return structure


def _split_references(lines: list[str]) -> list[str]:
    """Group raw reference lines into individual entries by [n]/n. markers."""
    refs: list[str] = []
    buffer = ""
    for line in lines:
        if _REF_MARKER.match(line):
            if buffer:
                refs.append(buffer.strip())
            buffer = _REF_MARKER.sub("", line)
        else:
            buffer = (buffer + " " + line).strip()
    if buffer:
        refs.append(buffer.strip())
    return [r for r in refs if r]


def _sections_matching(structure: PaperStructure, *keywords: str) -> list[PaperSection]:
    out: list[PaperSection] = []
    for section in structure.sections:
        low = section.title.lower()
        if any(kw in low for kw in keywords):
            out.append(section)
    return out


def _joined(sections: list[PaperSection], limit: int = 1200) -> str:
    return redact(" ".join(s.text for s in sections).strip())[:limit]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _sentences_with(structure: PaperStructure, *needles: str, limit: int = 6) -> list[str]:
    found: list[str] = []
    for section in structure.sections:
        for sentence in _sentences(section.text):
            low = sentence.lower()
            if any(n in low for n in needles):
                found.append(redact(sentence)[:300])
                if len(found) >= limit:
                    return found
    return found


def _theorem_mentions(structure: PaperStructure, limit: int = 8) -> list[str]:
    """Collect sentences that state a numbered theorem/lemma (any section)."""
    found: list[str] = []
    seen: set[str] = set()
    for section in structure.sections:
        if _is_references_title(section.title):
            continue
        for sentence in _sentences(section.text):
            if not _THEOREM_LINE.search(sentence):
                continue
            cleaned = redact(sentence)[:400]
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(cleaned)
            if len(found) >= limit:
                return found
    return found


def build_paper_note(
    paper_id: str, structure: PaperStructure, title: str | None = None
) -> PaperNote:
    """Populate the fixed note schema from extracted structure (deterministic)."""
    contrib = _sections_matching(structure, "abstract", "introduction")
    method = _sections_matching(structure, "method", "approach", "model", "theory")
    results = _sections_matching(structure, "result", "evaluation", "experiment", "analysis")
    limitations = _sections_matching(structure, "limitation", "threats to validity")

    stated_limits = [_joined(limitations)] if limitations else []
    if not stated_limits:
        stated_limits = _sentences_with(structure, "limitation", "however", "cannot")

    key_results = _joined(results)
    theorem_pages: list[int] = []
    if not key_results.strip():
        theorems = _theorem_mentions(structure)
        if theorems:
            key_results = "\n".join(f"- {t}" for t in theorems)
            theorem_pages = sorted(
                {
                    section.page
                    for section in structure.sections
                    if section.text and _THEOREM_LINE.search(section.text)
                }
            )

    provenance: dict[str, list[int]] = {}
    key_result_sections = (
        results
        if key_results == _joined(results)
        else [s for s in structure.sections if s.text and _THEOREM_LINE.search(s.text)]
    )
    for field, secs in (
        ("contribution", contrib),
        ("method", method),
        ("key_results", key_result_sections),
        ("stated_limitations", limitations),
    ):
        pages = sorted({s.page for s in secs})
        if field == "key_results" and theorem_pages and not pages:
            pages = theorem_pages
        if pages:
            provenance[field] = pages

    return PaperNote(
        paper_id=paper_id,
        title=title,
        contribution=_joined(contrib),
        method=_joined(method),
        assumptions=_sentences_with(structure, "assume", "assumption", "we suppose"),
        key_results=key_results,
        datasets=_dataset_mentions(structure),
        stated_limitations=[s for s in stated_limits if s],
        provenance=provenance,
    )


def _dataset_mentions(structure: PaperStructure, limit: int = 8) -> list[str]:
    mentions: list[str] = []
    seen: set[str] = set()
    for sentence in _sentences_with(structure, "dataset", "benchmark", "corpus", limit=limit):
        key = sentence.lower()
        if key not in seen:
            seen.add(key)
            mentions.append(sentence)
    return mentions


def render_note_markdown(note: PaperNote) -> str:
    """Render the note as a disciplined Markdown reading note with provenance."""

    def prov(field: str) -> str:
        pages = note.provenance.get(field)
        return f" _(pp. {', '.join(map(str, pages))})_" if pages else ""

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- (none stated)"

    return (
        f"# {note.paper_id} — {note.title or '(untitled)'}\n\n"
        "> Reading note: extracted **evidence**, not a verified claim. Distinguishes\n"
        "> what the authors *state* from what is *demonstrated*.\n\n"
        f"## Contribution{prov('contribution')}\n\n{note.contribution or '(not found)'}\n\n"
        f"## Method{prov('method')}\n\n{note.method or '(not found)'}\n\n"
        f"## Key results (as reported){prov('key_results')}\n\n"
        f"{note.key_results or '(not found)'}\n\n"
        f"## Assumptions\n\n{bullets(note.assumptions)}\n\n"
        f"## Datasets / benchmarks\n\n{bullets(note.datasets)}\n\n"
        f"## Stated limitations{prov('stated_limitations')}\n\n{bullets(note.stated_limitations)}\n"
    )
