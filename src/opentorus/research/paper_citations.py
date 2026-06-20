"""Validate PAPER-* and theorem references against locally parsed paper text."""

from __future__ import annotations

import json
import re
from pathlib import Path

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


def _paper_corpus(ot_dir: Path, paper_id: str) -> str | None:
    """Return lowercased searchable text for a parsed PAPER-* or None."""
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
    return joined.lower() if joined else None


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

    paper_ids = sorted({m.upper() for m in _PAPER_ID.findall(body)})
    for pid in paper_ids:
        corpus = _paper_corpus(ot_dir, pid)
        if corpus is None:
            errors.append(
                f"{pid} is cited but has no parsed full text — "
                "call paper_fetch and ensure [parsed]."
            )
            continue

        theorems = cited_theorems_for_paper(body, pid)
        for thm in sorted(theorems):
            if not theorem_in_corpus(corpus, thm):
                errors.append(
                    f"{pid} does not contain Theorem/Lemma {thm} in parsed text — "
                    "do not invent theorem numbers; cite what the reading note shows."
                )

        if pid in body and not theorems:
            warnings.append(
                f"{pid} is mentioned without a specific theorem/lemma number — "
                "prefer citing a parsed result (e.g. Theorem 2.1, p.5)."
            )

    return errors, warnings
