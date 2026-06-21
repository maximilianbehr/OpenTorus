"""Evasion-resistant text normalization for scanners.

The honesty linters and the DLP secret scanner match patterns against text. Naive
matching is defeated by two cheap tricks: zero-width characters that split a
banned token (``we pr<ZWSP>oven``), and Unicode homoglyphs that render identically
to ASCII (Cyrillic ``о`` for Latin ``o``). :func:`normalize_for_scan` folds both —
plus NFKC compatibility forms (fullwidth, ligatures) — before matching.

Line structure is preserved: newlines are never touched and characters are mapped
one-for-one except for removed zero-width/format marks, so a caller may normalize
per line and keep 1-based line numbers accurate.
"""

from __future__ import annotations

import unicodedata

# Zero-width / joiner characters used to split a token past a matcher.
_ZERO_WIDTH: frozenset[str] = frozenset(
    {
        "​",  # zero-width space
        "‌",  # zero-width non-joiner
        "‍",  # zero-width joiner
        "⁠",  # word joiner
        "﻿",  # zero-width no-break space / BOM
        "­",  # soft hyphen
    }
)

# Curated Latin-confusable homoglyphs (Cyrillic / Greek) -> ASCII. Conservative:
# only code points that are visually identical to a Latin letter in common fonts.
_CONFUSABLES: dict[str, str] = {
    # Cyrillic lowercase
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "х": "x",
    "у": "y",
    "і": "i",
    "ј": "j",
    # Cyrillic uppercase
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "Х": "X",
    "Ѕ": "S",
    # Greek lowercase
    "ο": "o",
    "α": "a",
    "ε": "e",
    "ρ": "p",
    "υ": "u",
    # Greek uppercase
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Χ": "X",
}


def normalize_for_scan(text: str) -> str:
    """Fold zero-width splits, homoglyphs, and compatibility forms for pattern matching."""
    text = unicodedata.normalize("NFKC", text)
    out: list[str] = []
    for ch in text:
        if ch in _ZERO_WIDTH:
            continue
        # Drop other format (Cf) controls (e.g. bidi overrides) but keep newlines.
        if ch != "\n" and unicodedata.category(ch) == "Cf":
            continue
        out.append(_CONFUSABLES.get(ch, ch))
    return "".join(out)
