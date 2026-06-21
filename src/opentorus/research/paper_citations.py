"""Validate PAPER-* and theorem references against locally parsed paper text."""

from __future__ import annotations

import json
import re
from pathlib import Path

# Unicode hyphens/dashes a model may type in "PAPER-0001" (e.g. U+2011 non-breaking
# hyphen). Normalize to ASCII before matching so the citation grounding guard is not
# silently bypassed by typographic hyphens (mirrors nl_proof._HYPHENS).
_HYPHEN_MAP = {ord(c): "-" for c in "‐‑‒–—―−"}


def _normalize_hyphens(text: str) -> str:
    return text.translate(_HYPHEN_MAP)


_PAPER_ID = re.compile(r"PAPER-\d{4}", re.I)
_THM_NUM = re.compile(r"(\d+(?:\.\d+)*)")
_THM_LABEL = re.compile(
    r"\b(Theorem|Lemma|Proposition|Corollary)\s+(\d+(?:\.\d+)*)",
    re.I,
)
_THM_IN_TEXT = re.compile(
    r"\b(theorem|lemma|proposition|corollary)\s+(\d+(?:\.\d+)*)",
    re.I,
)
# "Theorem 3.1 in PAPER-0005", "PAPER-0005 ... Theorem 3.1", "PAPER-0005-THM-3.1"
_CITE_PATTERNS = (
    re.compile(
        r"(?:Theorem|Lemma|Proposition|Corollary)\s+(\d+(?:\.\d+)*)"
        rf"[^.\n]{{0,120}}{_PAPER_ID.pattern}",
        re.I,
    ),
    re.compile(
        rf"{_PAPER_ID.pattern}[^.\n]{{0,120}}"
        r"(?:Theorem|Lemma|Proposition|Corollary)\s+(\d+(?:\.\d+)*)",
        re.I,
    ),
    re.compile(rf"{_PAPER_ID.pattern}-THM-(\d+(?:\.\d+)*)", re.I),
)


def _paper_corpus(ot_dir: Path, paper_id: str, *, lower: bool = True) -> str | None:
    """Return searchable text for a parsed PAPER-* (lowercased by default) or None."""
    from opentorus.research.papers import get_paper, is_paper_parsed

    paper = get_paper(ot_dir, paper_id.upper())
    if paper is None or not is_paper_parsed(ot_dir, paper):
        return None

    parts: list[str] = []
    if paper.structure_path:
        path = ot_dir / paper.structure_path
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            abstract = data.get("abstract")
            if isinstance(abstract, str) and abstract.strip():
                parts.append(abstract)
            for section in data.get("sections") or []:
                if isinstance(section, dict):
                    text = section.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)

    if paper.text_path:
        text_path = ot_dir / paper.text_path
        if text_path.is_file():
            try:
                parts.append(text_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass

    if paper.summary_path:
        note_path = ot_dir / paper.summary_path
        if note_path.is_file():
            try:
                parts.append(note_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass

    joined = "\n".join(parts).strip()
    if not joined:
        return None
    return joined.lower() if lower else joined


def theorem_context(corpus_raw: str, number: str, *, width: int = 220) -> str | None:
    """Return a short readable snippet around 'Theorem <number>' in the raw corpus.

    Lets a reviewer/referee check that a cited statement actually matches the source,
    rather than only that the theorem *number* exists. Non-blocking and best-effort.
    """
    if not corpus_raw or not number:
        return None
    num = re.escape(number.strip())
    m = re.search(rf"\b(?:theorem|lemma|proposition|corollary)\s+{num}\b", corpus_raw, re.I)
    if m is None:
        return None
    start = max(0, m.start() - 20)
    snippet = " ".join(corpus_raw[start : m.start() + width].split())
    return snippet[:width].strip()


def theorem_in_corpus(corpus: str, number: str) -> bool:
    """True when ``Theorem <number>`` (or lemma/…) appears in parsed text."""
    if not corpus or not number:
        return False
    num = re.escape(number.strip())
    return bool(
        re.search(
            rf"\b(?:theorem|lemma|proposition|corollary)\s+{num}(?:\b|[\s,.;)]|$)",
            corpus,
            re.I,
        )
    )


def cited_theorems_for_paper(body: str, paper_id: str) -> set[str]:
    """Heuristically extract theorem numbers attributed to one PAPER-* id."""
    pid = paper_id.upper()
    found: set[str] = set()
    for pattern in _CITE_PATTERNS:
        for match in pattern.finditer(body):
            groups = match.groups()
            if not groups:
                continue
            paper_ref = next((g for g in groups if g and g.upper().startswith("PAPER-")), None)
            thm_ref = next((g for g in groups if g and _THM_NUM.fullmatch(g)), None)
            if paper_ref and paper_ref.upper() != pid:
                continue
            if thm_ref:
                found.add(thm_ref)
    # Also scan windows around each mention of the paper id.
    for match in re.finditer(re.escape(pid), body, re.I):
        window = body[max(0, match.start() - 80) : match.end() + 120]
        for thm in _THM_LABEL.finditer(window):
            found.add(thm.group(2))
    return found


def validate_proof_citations(ot_dir: Path, body: str) -> tuple[list[str], list[str]]:
    """Return ``(blocking_errors, warnings)`` for proof text citing PAPER-* artifacts."""
    errors: list[str] = []
    warnings: list[str] = []
    if not body.strip():
        return errors, warnings

    # Normalize typographic hyphens so "Paper‑0001" (U+2011) is still validated.
    body = _normalize_hyphens(body)
    paper_ids = sorted({m.upper() for m in _PAPER_ID.findall(body)})
    for pid in paper_ids:
        # Unverifiable author/year attribution is independent of parse status.
        warnings.extend(_year_attribution_warnings(ot_dir, body, pid))

        corpus = _paper_corpus(ot_dir, pid)
        if corpus is None:
            errors.append(
                f"{pid} is cited but has no parsed full text — "
                "call paper_fetch and ensure [parsed]."
            )
            continue

        theorems = cited_theorems_for_paper(body, pid)
        corpus_raw: str | None = None
        for thm in sorted(theorems):
            if not theorem_in_corpus(corpus, thm):
                errors.append(
                    f"{pid} does not contain Theorem/Lemma {thm} in parsed text — "
                    "do not invent theorem numbers; cite what the reading note shows."
                )
                continue
            # The number exists; surface the source sentence as a non-blocking advisory
            # so a reviewer can confirm the cited *statement* matches (not just the id).
            if corpus_raw is None:
                corpus_raw = _paper_corpus(ot_dir, pid, lower=False) or ""
            context = theorem_context(corpus_raw, thm)
            if context:
                warnings.append(
                    f"{pid} Theorem/Lemma {thm} source context (verify the cited statement "
                    f"matches): “{context}”"
                )

        if pid in body and not theorems:
            warnings.append(
                f"{pid} is mentioned without a specific theorem/lemma number — "
                "prefer citing a parsed result (e.g. Theorem 2.1, p.5)."
            )

    return errors, warnings


# --- Persisted citation-failure memory (so a fabricated theorem number is not
# re-invented after the context is compacted away). -----------------------------


def _citation_failures_path(ot_dir: Path, problem_id: str) -> Path:
    from opentorus.research.dossier import store

    return store.dossier_dir(ot_dir, problem_id.strip().upper()) / "citation_failures.txt"


def known_bad_citations(ot_dir: Path, problem_id: str) -> list[str]:
    """Citations a prior proof_write tried that the parsed sources do not contain."""
    path = _citation_failures_path(ot_dir, problem_id)
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def record_citation_failures(ot_dir: Path, problem_id: str, errors: list[str]) -> list[str]:
    """Persist the fabricated-citation errors for a dossier; return the merged list.

    Only "does not contain Theorem/Lemma N" errors are recorded (a genuinely
    nonexistent citation), deduplicated and shortened, so the prove loop can re-feed
    them on later attempts instead of letting the model re-invent the same numbers
    after a compaction drops the earlier rejection.
    """
    from opentorus.research.dossier import store

    pid = problem_id.strip().upper()
    if store.get_dossier(ot_dir, pid) is None:
        return []
    fresh = [_short_citation_failure(e) for e in errors if "does not contain" in e]
    fresh = [f for f in fresh if f]
    if not fresh:
        return known_bad_citations(ot_dir, pid)
    merged = list(dict.fromkeys(known_bad_citations(ot_dir, pid) + fresh))
    from opentorus.atomicio import atomic_write_text

    atomic_write_text(_citation_failures_path(ot_dir, pid), "\n".join(merged) + "\n")
    return merged


def _short_citation_failure(error: str) -> str:
    """Reduce a verbose citation error to the load-bearing 'PAPER-X has no Theorem N'."""
    text = error.strip()
    for sep in (" in parsed text", " — ", " - "):
        if sep in text:
            text = text.split(sep)[0]
            break
    return text.strip()[:140]


# A year token attached to a PAPER-* mention, e.g. "PAPER-0001 (Kressner, 2020)".
_YEAR_NEAR = re.compile(r"(?:19|20)\d{2}")


def _year_attribution_warnings(ot_dir: Path, body: str, pid: str) -> list[str]:
    """Warn when a proof attaches an author/year a local artifact cannot confirm.

    A specific year tied to a ``PAPER-*`` whose metadata records no (matching) year is
    an unverifiable attribution (the "Kressner & Tobler, 2020" class). Non-blocking: it
    surfaces invented authorship without rejecting an otherwise-grounded proof.
    """
    from opentorus.research.papers import get_paper

    paper = get_paper(ot_dir, pid)
    meta_year = str(paper.year) if (paper and paper.year) else None
    cited: set[str] = set()
    for match in re.finditer(re.escape(pid), body, re.I):
        window = body[match.start() : min(len(body), match.end() + 40)]
        cited.update(y for y in _YEAR_NEAR.findall(window) if y != meta_year)
    if not cited:
        return []
    return [
        f"{pid} is attributed a year ({', '.join(sorted(cited))}) the local metadata "
        "does not record — verify against the source; do not invent author/year."
    ]
