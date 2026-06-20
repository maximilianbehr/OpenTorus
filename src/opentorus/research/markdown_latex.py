"""Prepare Markdown with Unicode math for high-quality PDF export via pandoc."""

from __future__ import annotations

import re
import unicodedata

from opentorus.research.authoring import UNICODE_MATH, UNICODE_TEXT

# Extra symbols common in NL proofs but absent from the report LaTeX map.
_EXTRA_UNICODE_MATH: dict[str, str] = {
    "‖": r"\|",
    "∥": r"\|",
    "⟨": r"\langle",
    "⟩": r"\rangle",
    "∧": r"\land",
    "∨": r"\lor",
    "⊗": r"\otimes",
    "⊕": r"\oplus",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "∂": r"\partial",
    "∇": r"\nabla",
    "∀": r"\forall",
    "∃": r"\exists",
    "∅": r"\emptyset",
    "≡": r"\equiv",
    "≪": r"\ll",
    "≫": r"\gg",
    "∼": r"\sim",
    "≃": r"\simeq",
    "⊆": r"\subseteq",
    "⊇": r"\supseteq",
    "∪": r"\cup",
    "∩": r"\cap",
    "⊥": r"\perp",
    "⌊": r"\lfloor",
    "⌋": r"\rfloor",
    "⌈": r"\lceil",
    "⌉": r"\rceil",
    "ℓ": r"\ell",
    "κ": r"\kappa",
    "ϵ": r"\epsilon",
    "ε": r"\varepsilon",
    "−": "-",
    "–": "--",
    "—": "---",
}

_UNICODE_MATH_ALL = {**UNICODE_MATH, **_EXTRA_UNICODE_MATH}

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

_COMBINING = {
    "\u0300": r"\grave",
    "\u0301": r"\acute",
    "\u0302": r"\hat",
    "\u0303": r"\tilde",
    "\u0304": r"\bar",
    "\u0306": r"\breve",
    "\u0307": r"\dot",
    "\u0308": r"\ddot",
    "\u030c": r"\check",
}

# Protect fenced code and inline code from math conversion.
_FENCE_RE = re.compile(r"(```[\s\S]*?```|`[^`\n]+`)")

# Pandoc's `tex_math_dollars` alone does not treat `\(...\)` / `\[...\]` as math.
_LATEX_PAREN_INLINE_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_LATEX_PAREN_DISPLAY_RE = re.compile(r"\\\[([\s\S]+?)\\\]", re.DOTALL)

# Typography — must not become `$---$` inline math runs.
_TYPOGRAPHY_DASHES = frozenset("−–—")

# ASCII TeX-ish fragments common in NL proofs (keep intact; wrap for pandoc).
_BRACE_EXPONENT_RE = re.compile(r"([A-Za-z])\^\{([^{}]+)\}")
_BRACE_SUBSCRIPT_RE = re.compile(r"([A-Za-z)\]|\\|])\)_\{([^{}]+)\}")
_LATEX_CMD_RE = re.compile(
    r"\\(?:mathcal|mathbb|mathrm|mathit|mathfrak|"
    r"in|times|leq|geq|le|ge|neq|approx|varepsilon|epsilon|Omega|min|max|tilde|frac|sqrt|log|det|arg|mod|bmod|pm)\b"
)


def _normalize_tex_math_delimiters(text: str) -> str:
    """Map LaTeX-style math delimiters to `$…$` / `$$…$$` for pandoc."""
    text = _LATEX_PAREN_DISPLAY_RE.sub(lambda m: f"$$\n{m.group(1).strip()}\n$$", text)
    text = _LATEX_PAREN_INLINE_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
    return text


def _protect_ascii_latex(text: str) -> str:
    """Wrap common ASCII math fragments so Unicode heuristics do not split them."""
    text = _BRACE_EXPONENT_RE.sub(r"$\1^{\2}$", text)
    text = _BRACE_SUBSCRIPT_RE.sub(r"$\1_{\2}$", text)
    return _LATEX_CMD_RE.sub(lambda m: f"${m.group(0)}$", text)


def _char_to_latex(ch: str) -> str | None:
    if ch in _UNICODE_MATH_ALL:
        return _UNICODE_MATH_ALL[ch]
    if ch in UNICODE_TEXT:
        return UNICODE_TEXT[ch]
    if ch in "⁰¹²³⁴⁵⁶⁷⁸⁹":
        return f"^{{{ch.translate(_SUPERSCRIPT)}}}"
    if ch in "₀₁₂₃₄₅₆₇₈₉":
        return f"_{{{ch.translate(_SUBSCRIPT)}}}"
    cat = unicodedata.category(ch)
    if cat in {"Lu", "Ll", "Nd"} and ord(ch) < 128:
        return ch
    if cat == "Zs":
        return " "
    return None


def _apply_combining(text: str) -> str:
    """Turn base+combining sequences (e.g. X̃) into LaTeX accents."""
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if i + 1 < len(text) and text[i + 1] in _COMBINING:
            base = ch
            comb = text[i + 1]
            cmd = _COMBINING[comb]
            if base.isalpha():
                out.append(f"\\{cmd}{{{base}}}")
            else:
                out.append(ch + comb)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _convert_math_run(run: str) -> str:
    run = _apply_combining(run)
    tokens: list[str] = []
    for ch in run:
        mapped = _char_to_latex(ch)
        # Non-ascii unknown: keep as unicode text when the LaTeX engine supports UTF-8.
        tokens.append(ch if mapped is None else mapped)
    # Join, inserting a space where a control word (e.g. \in, \cdot, \rho) would
    # otherwise glue to a following letter and form an undefined command:
    # ``∈C`` -> ``\in`` + ``C`` must become ``\in C`` (renders ∈C), not ``\inC``.
    pieces: list[str] = []
    for tok in tokens:
        if pieces and tok[:1].isalpha() and re.search(r"\\[A-Za-z]+$", pieces[-1]):
            pieces.append(" ")
        pieces.append(tok)
    body = "".join(pieces).strip()
    if not body:
        return run
    return f"${body}$"


def _latex_inner(text: str) -> str:
    text = _apply_combining(text.strip())
    parts: list[str] = []
    for ch in text:
        mapped = _char_to_latex(ch)
        parts.append(mapped if mapped is not None else ch)
    return "".join(parts)


def _convert_frobenius_norms(text: str) -> str:
    """Turn ‖·‖_F patterns into a single math block."""

    def repl(match: re.Match[str]) -> str:
        inner = _latex_inner(match.group(1))
        sub = match.group(2) or ""
        return f"$\\|{inner}\\|{sub}$"

    return re.sub(r"‖([^‖]+)‖(_F)?", repl, text)


def _convert_unicode_runs(segment: str) -> str:
    """Wrap contiguous unicode-math characters in a single inline math block."""
    if not segment.strip():
        return segment

    # Only Unicode symbols start new math runs — not ASCII ^ { ( ) etc.
    math_chars = set(_UNICODE_MATH_ALL) - _TYPOGRAPHY_DASHES | set("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉")

    def convert_plain(text: str) -> str:
        text = _normalize_tex_math_delimiters(text)
        text = _protect_ascii_latex(text)
        text = _convert_frobenius_norms(text)
        text = _apply_combining(text)
        out: list[str] = []
        buf: list[str] = []

        def flush() -> None:
            if not buf:
                return
            out.append(_convert_math_run("".join(buf)))
            buf.clear()

        i = 0
        while i < len(text):
            ch = text[i]
            if ch in ".,;:!?":
                flush()
                out.append(ch)
                i += 1
                continue
            if ch in _TYPOGRAPHY_DASHES:
                flush()
                out.append({"−": "-", "–": "--", "—": "---"}[ch])
                i += 1
                continue
            if ch in math_chars or (buf and ch.isalnum()):
                buf.append(ch)
                i += 1
                continue
            flush()
            out.append(ch)
            i += 1
        flush()
        return "".join(out)

    parts = re.split(r"(\$[^$]+\$)", segment)
    return "".join(part if idx % 2 == 1 else convert_plain(part) for idx, part in enumerate(parts))


def prepare_markdown_for_pdf(markdown: str) -> str:
    """Normalize Unicode math/typography so pandoc+xelatex render cleanly."""
    markdown = _normalize_tex_math_delimiters(markdown)
    parts = _FENCE_RE.split(markdown)
    converted: list[str] = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            converted.append(part)
        else:
            converted.append(_convert_unicode_runs(part))
    return "".join(converted)


PANDOC_MARKDOWN_FORMAT = "markdown+tex_math_dollars+tex_math_single_backslash+smart+pipe_tables"


PANDOC_YAML_MINIMAL = """\
---
documentclass: article
geometry: margin=1in
fontsize: 11pt
colorlinks: true
header-includes:
  - '\\usepackage{amsmath,amssymb,amsfonts}'
---
"""

# Optional; requires a full TeX Live install (lm + unicode-math packages).
PANDOC_YAML_WITH_FONTS = """\
---
documentclass: article
geometry: margin=1in
fontsize: 11pt
mainfont: Latin Modern Roman
sansfont: Latin Modern Sans
monofont: Latin Modern Mono
mathfont: Latin Modern Math
colorlinks: true
header-includes:
  - '\\usepackage{amsmath,amssymb,amsfonts}'
---
"""

# Default export header — no named system fonts (works with BasicTeX on macOS).
PANDOC_YAML_HEADER = PANDOC_YAML_MINIMAL


def pandoc_yaml_header(*, use_named_fonts: bool = False) -> str:
    return PANDOC_YAML_WITH_FONTS if use_named_fonts else PANDOC_YAML_MINIMAL
