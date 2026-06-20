"""Render inline LaTeX math as readable Unicode for the terminal.

Model responses frequently contain LaTeX such as ``$a^{\\phi(n)} \\equiv 1
\\pmod{n}$``, which is hard to read in a plain terminal. This module rewrites the
*contents of math delimiters* (``$...$``, ``$$...$$``, ``\\(...\\)``,
``\\[...\\]``) into Unicode (``aᵠ⁽ⁿ⁾ … →`` style), leaving ordinary prose, code
spans, and fenced code blocks untouched.

Design choices that keep it safe:

* Only text inside math delimiters is transformed, so prose like ``snake_case``
  or ``a_b`` outside math is never mangled.
* Inline code spans (`` `...` ``) and fenced code blocks (``` ``` ```) are
  preserved verbatim.
* Unknown LaTeX commands degrade gracefully (the leading backslash is dropped)
  rather than raising.
"""

from __future__ import annotations

import re

_GREEK = {
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\varepsilon": "ε",
    r"\zeta": "ζ",
    r"\eta": "η",
    r"\theta": "θ",
    r"\vartheta": "ϑ",
    r"\iota": "ι",
    r"\kappa": "κ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\nu": "ν",
    r"\xi": "ξ",
    r"\pi": "π",
    r"\varpi": "ϖ",
    r"\rho": "ρ",
    r"\varrho": "ϱ",
    r"\sigma": "σ",
    r"\varsigma": "ς",
    r"\tau": "τ",
    r"\upsilon": "υ",
    r"\phi": "φ",
    r"\varphi": "φ",
    r"\chi": "χ",
    r"\psi": "ψ",
    r"\omega": "ω",
    r"\Gamma": "Γ",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Xi": "Ξ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Upsilon": "Υ",
    r"\Phi": "Φ",
    r"\Psi": "Ψ",
    r"\Omega": "Ω",
}

_OPS = {
    r"\equiv": "≡",
    r"\neq": "≠",
    r"\ne": "≠",
    r"\leq": "≤",
    r"\le": "≤",
    r"\geq": "≥",
    r"\ge": "≥",
    r"\ll": "≪",
    r"\gg": "≫",
    r"\approx": "≈",
    r"\sim": "∼",
    r"\simeq": "≃",
    r"\cong": "≅",
    r"\propto": "∝",
    r"\times": "×",
    r"\cdot": "·",
    r"\div": "÷",
    r"\pm": "±",
    r"\mp": "∓",
    r"\ast": "∗",
    r"\star": "⋆",
    r"\circ": "∘",
    r"\bullet": "•",
    r"\oplus": "⊕",
    r"\otimes": "⊗",
    r"\odot": "⊙",
    r"\to": "→",
    r"\rightarrow": "→",
    r"\longrightarrow": "⟶",
    r"\Rightarrow": "⇒",
    r"\implies": "⟹",
    r"\leftarrow": "←",
    r"\Leftarrow": "⇐",
    r"\iff": "⟺",
    r"\leftrightarrow": "↔",
    r"\Leftrightarrow": "⇔",
    r"\mapsto": "↦",
    r"\uparrow": "↑",
    r"\downarrow": "↓",
    r"\in": "∈",
    r"\notin": "∉",
    r"\ni": "∋",
    r"\subset": "⊂",
    r"\subseteq": "⊆",
    r"\subsetneq": "⊊",
    r"\supset": "⊃",
    r"\supseteq": "⊇",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\emptyset": "∅",
    r"\varnothing": "∅",
    r"\setminus": "∖",
    r"\forall": "∀",
    r"\exists": "∃",
    r"\nexists": "∄",
    r"\neg": "¬",
    r"\lnot": "¬",
    r"\land": "∧",
    r"\wedge": "∧",
    r"\lor": "∨",
    r"\vee": "∨",
    r"\infty": "∞",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\sum": "∑",
    r"\prod": "∏",
    r"\coprod": "∐",
    r"\int": "∫",
    r"\oint": "∮",
    r"\sqrt": "√",
    r"\angle": "∠",
    r"\perp": "⊥",
    r"\parallel": "∥",
    r"\langle": "⟨",
    r"\rangle": "⟩",
    r"\lfloor": "⌊",
    r"\rfloor": "⌋",
    r"\lceil": "⌈",
    r"\rceil": "⌉",
    r"\mid": "∣",
    r"\nmid": "∤",
    r"\dots": "…",
    r"\ldots": "…",
    r"\cdots": "⋯",
    r"\vdots": "⋮",
    r"\ddots": "⋱",
    r"\backslash": "\\",
    r"\Re": "ℜ",
    r"\Im": "ℑ",
    r"\aleph": "ℵ",
    r"\hbar": "ℏ",
    r"\ell": "ℓ",
    r"\wp": "℘",
    r"\prime": "′",
    r"\top": "⊤",
    r"\bot": "⊥",
    r"\models": "⊨",
    r"\vdash": "⊢",
    r"\doteq": "≐",
    r"\sqcup": "⊔",
    r"\sqcap": "⊓",
    r"\triangle": "△",
}

# Word commands that simply lose their backslash (functions and operators).
_FUNCS = {
    name: name[1:]
    for name in (
        r"\gcd",
        r"\lcm",
        r"\min",
        r"\max",
        r"\sup",
        r"\inf",
        r"\lim",
        r"\log",
        r"\ln",
        r"\lg",
        r"\exp",
        r"\sin",
        r"\cos",
        r"\tan",
        r"\cot",
        r"\sec",
        r"\csc",
        r"\sinh",
        r"\cosh",
        r"\tanh",
        r"\det",
        r"\dim",
        r"\deg",
        r"\ker",
        r"\arg",
        r"\hom",
        r"\Pr",
        r"\bmod",
        r"\mod",
    )
}
_FUNCS[r"\bmod"] = "mod"

# Spacing / grouping commands that are simply dropped.
_DROP = {
    name: ""
    for name in (
        r"\left",
        r"\right",
        r"\big",
        r"\Big",
        r"\bigg",
        r"\Bigg",
        r"\bigl",
        r"\bigr",
        r"\quad",
        r"\qquad",
        r"\,",
        r"\;",
        r"\:",
        r"\!",
        r"\displaystyle",
        r"\textstyle",
        r"\limits",
        r"\nolimits",
    )
}
_DROP[r"\quad"] = "  "
_DROP[r"\qquad"] = "    "

_WORD: dict[str, str] = {**_GREEK, **_OPS, **_FUNCS, **_DROP}

_MATHBB = {
    "R": "ℝ",
    "Z": "ℤ",
    "N": "ℕ",
    "Q": "ℚ",
    "C": "ℂ",
    "P": "ℙ",
    "H": "ℍ",
    "F": "𝔽",
    "E": "𝔼",
    "D": "𝔻",
    "K": "𝕂",
}

_SUP = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
    "+": "⁺",
    "-": "⁻",
    "=": "⁼",
    "(": "⁽",
    ")": "⁾",
    "n": "ⁿ",
    "i": "ⁱ",
    "a": "ᵃ",
    "b": "ᵇ",
    "c": "ᶜ",
    "d": "ᵈ",
    "e": "ᵉ",
    "f": "ᶠ",
    "g": "ᵍ",
    "h": "ʰ",
    "j": "ʲ",
    "k": "ᵏ",
    "l": "ˡ",
    "m": "ᵐ",
    "o": "ᵒ",
    "p": "ᵖ",
    "r": "ʳ",
    "s": "ˢ",
    "t": "ᵗ",
    "u": "ᵘ",
    "v": "ᵛ",
    "w": "ʷ",
    "x": "ˣ",
    "y": "ʸ",
    "z": "ᶻ",
    "T": "ᵀ",
}

_SUB = {
    "0": "₀",
    "1": "₁",
    "2": "₂",
    "3": "₃",
    "4": "₄",
    "5": "₅",
    "6": "₆",
    "7": "₇",
    "8": "₈",
    "9": "₉",
    "+": "₊",
    "-": "₋",
    "=": "₌",
    "(": "₍",
    ")": "₎",
    "a": "ₐ",
    "e": "ₑ",
    "h": "ₕ",
    "i": "ᵢ",
    "j": "ⱼ",
    "k": "ₖ",
    "l": "ₗ",
    "m": "ₘ",
    "n": "ₙ",
    "o": "ₒ",
    "p": "ₚ",
    "r": "ᵣ",
    "s": "ₛ",
    "t": "ₜ",
    "u": "ᵤ",
    "v": "ᵥ",
    "x": "ₓ",
}

_ESCAPED = re.compile(r"\\([$%&#_{}])")
_WORD_RE = re.compile(r"\\[a-zA-Z]+")
# A single ^ or _ followed by either a {group} or one character. Processing both
# in one pass (re.sub never rescans replacements) avoids re-converting the
# parentheses of a "^(...)" fallback.
_SCRIPT_RE = re.compile(r"([\^_])(\{[^{}]*\}|\S)")
_MATH_SPAN = re.compile(
    r"\$\$(.+?)\$\$|\$(.+?)\$|\\\[(.+?)\\\]|\\\((.+?)\\\)",
    re.DOTALL,
)
_CODE_SPAN = re.compile(r"(`[^`]*`)")


def _script_sub(match: re.Match[str]) -> str:
    marker, body = match.group(1), match.group(2)
    table = _SUP if marker == "^" else _SUB
    if body.startswith("{"):
        content = body[1:-1]
        fallback = f"{marker}({content})"
    else:
        content = body
        fallback = f"{marker}{content}"
    mapped = [table.get(ch) for ch in content]
    if content and all(m is not None for m in mapped):
        return "".join(m for m in mapped if m is not None)
    return fallback


def _word_sub(match: re.Match[str]) -> str:
    token = match.group(0)
    if token in _WORD:
        return _WORD[token]
    return token[1:]  # unknown command: drop the backslash


def _mathbb_sub(match: re.Match[str]) -> str:
    content = match.group(1)
    return _MATHBB.get(content, content)


def _convert(s: str) -> str:
    """Convert the inside of a single math span to Unicode."""
    s = s.replace("\\\\", " ")
    s = _ESCAPED.sub(lambda m: m.group(1), s)
    s = re.sub(r"\\pmod\{([^{}]*)\}", r"(mod \1)", s)
    s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", s)
    s = re.sub(
        r"\\(?:text|mathrm|mathbf|mathit|mathsf|mathtt|mathcal|operatorname)"
        r"\{([^{}]*)\}",
        r"\1",
        s,
    )
    s = re.sub(r"\\mathbb\{([^{}]*)\}", _mathbb_sub, s)
    s = _WORD_RE.sub(_word_sub, s)
    s = _SCRIPT_RE.sub(_script_sub, s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _span_sub(match: re.Match[str]) -> str:
    content = next(g for g in match.groups() if g is not None)
    return _convert(content)


def render_math_line(line: str) -> str:
    """Render math delimiters in a single line, leaving code spans intact."""
    parts = _CODE_SPAN.split(line)
    return "".join(
        part if part.startswith("`") else _MATH_SPAN.sub(_span_sub, part) for part in parts
    )


def render_math(text: str) -> str:
    """Render math in a multi-line string, skipping fenced code blocks."""
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
        elif in_fence:
            out.append(line)
        else:
            out.append(render_math_line(line))
    return "\n".join(out)
