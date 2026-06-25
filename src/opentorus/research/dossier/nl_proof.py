"""Natural-language proof templates for problem dossiers."""

from __future__ import annotations

import re
from typing import Literal

ProofScope = Literal["primary", "exploration"]

# Sections the honesty linter and reviewers expect in an NL proof artifact.
NL_PROOF_SECTIONS = (
    "Theorem",
    "Connection to dossier",
    "Definitions",
    "Lemmas",
    "Main proof",
    "Gaps and limitations",
    "Supporting evidence (not proof)",
)

# Matches a gap marker and any inline ``: description`` up to the closing
# bracket, so both ``[GAP-1]`` and ``[GAP-1: quantitative bound on …]`` are
# captured. Requiring a number and/or a colon-led description (not a bare space)
# keeps it from matching ordinary bracketed prose such as ``[gap between
# eigenvalues]`` — the spectral "gap" is common in this domain.
# Accept ASCII '-' and the Unicode hyphens/dashes a model may emit (e.g. U+2011
# non-breaking hyphen in "[GAP-1]"); an ASCII-only class silently under-counts gaps.
# Char class: literal '-', the U+2010–U+2015 hyphen/dash block, and U+2212 minus.
_HYPHENS = "-‐-―−"
_GAP_MARKER = re.compile(rf"\[GAP(?:[{_HYPHENS}\s]?\d+)?(?::[^\]]*)?\]", re.I)
_CONNECTION_HEADING = re.compile(r"^##\s+Connection to dossier\s*$", re.M | re.I)
_MIN_BRIDGE_CHARS = 60

_STOPWORDS = frozenset(
    {
        "what",
        "with",
        "from",
        "that",
        "this",
        "have",
        "been",
        "will",
        "into",
        "such",
        "only",
        "also",
        "when",
        "where",
        "which",
        "problem",
        "notes",
        "consider",
        "determining",
        "function",
        "number",
        "matrix",
        "matrices",
    }
)

_LATEX_STRIP = re.compile(r"\\[a-zA-Z]+(?:\{[^}]*\})?")

_OFF_TOPIC_CHECKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfredholm\b|\bvolterra\b", re.I), "Fredholm/Volterra integral equations"),
    (re.compile(r"tensor\s+network|renormalization\s+group", re.I), "tensor network methods"),
    (
        re.compile(r"software\s+engineering|machine\s+learning\s+in\s+software", re.I),
        "software-engineering surveys",
    ),
    (
        re.compile(r"\bhirsch\b|polytope\s+(?:graph\s+)?diameter", re.I),
        "polytope diameter / Hirsch",
    ),
    (re.compile(r"mathematical\s+universe|MUH\b|Tegmark", re.I), "MUH / philosophy papers"),
)


def _focus_terms(statement: str) -> set[str]:
    """Salient terms from a dossier statement for relevance matching."""
    raw = statement.lower()
    terms: set[str] = set()
    if "sign" in raw:
        terms.add("sign")
    if "delta" in raw or "\\delta" in statement:
        terms.add("delta")
    if "varepsilon" in raw or "epsilon" in raw or "\\varepsilon" in statement:
        terms.add("varepsilon")
    if "polynomial" in raw or "poly" in raw:
        terms.add("polynomial")
    if "approximat" in raw:
        terms.add("approximat")
    if "asymptot" in raw:
        terms.add("asymptot")
    if "matrix" in raw:
        terms.add("matrix")
    if "minimax" in raw or "chebyshev" in raw:
        terms.add("minimax")
    if "lanczos" in raw:
        terms.add("lanczos")
    if "error" in raw or "bound" in raw:
        terms.add("error")

    cleaned = _LATEX_STRIP.sub(" ", raw)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    for word in cleaned.split():
        if len(word) >= 5 and word not in _STOPWORDS:
            terms.add(word)
    return terms


def _connection_section_text(body: str, *, connection_to_dossier: str = "") -> str:
    """Return explicit bridge text from a field or a ``## Connection to dossier`` section."""
    extra = connection_to_dossier.strip()
    if extra:
        return extra
    match = _CONNECTION_HEADING.search(body)
    if not match:
        return ""
    tail = body[match.end() :]
    next_heading = re.search(r"^##\s+", tail, re.M)
    chunk = tail[: next_heading.start()] if next_heading else tail
    return chunk.strip()


def validate_proof_relevance(
    statement: str,
    body: str,
    *,
    title: str = "",
    scope: ProofScope = "primary",
    connection_to_dossier: str = "",
) -> tuple[list[str], list[str]]:
    """Return ``(blocking_errors, warnings)`` for topic alignment vs the dossier.

    **primary** — must directly address the dossier statement (the required answer).
    **exploration** — may pursue a different topic if an explicit bridge to the
    dossier is provided (speculative connections welcome; must not be confused
    with the primary answer).
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not statement.strip() or not body.strip():
        return errors, warnings

    combined = f"{title}\n{body}".lower()
    stmt_lower = statement.lower()
    focus = _focus_terms(statement)
    bridge = _connection_section_text(body, connection_to_dossier=connection_to_dossier)
    bridge_lower = bridge.lower()

    if scope == "exploration":
        if len(bridge) < _MIN_BRIDGE_CHARS:
            errors.append(
                "Exploration proofs require connection_to_dossier (≥60 chars) or a "
                "## Connection to dossier section explaining how this thread relates "
                "to the dossier problem. Mark gaps with [GAP-n] — do not present "
                "exploration as the dossier answer."
            )
        elif focus and not any(w in bridge_lower for w in focus):
            sample = ", ".join(sorted(focus)[:6])
            errors.append(
                "Connection to dossier must mention the dossier problem "
                f"(e.g. terms such as: {sample})."
            )
        for pattern, label in _OFF_TOPIC_CHECKS:
            if pattern.search(combined) and not pattern.search(stmt_lower):
                warnings.append(
                    f"Exploration uses {label} — keep scope=exploration and cite gaps; "
                    "also maintain a separate scope=primary sketch for the dossier."
                )
        if focus:
            hits = sorted(w for w in focus if w in combined)
            if len(hits) < 1:
                warnings.append(
                    "Exploration body does not reuse dossier vocabulary — ensure the "
                    "bridge section states the hypothesized link clearly."
                )
        return errors, warnings

    # --- primary scope (default deliverable) ---
    if focus:
        hits = sorted(w for w in focus if w in combined)
        min_hits = 1 if len(focus) <= 3 else min(2, len(focus))
        if len(hits) < min_hits:
            sample = ", ".join(sorted(focus)[:8])
            errors.append(
                "Primary proof does not address the dossier problem "
                f"(expected terms such as: {sample}; found {len(hits)}). "
                "Restate the theorem from statement.md. "
                "If you found a speculative side thread, save it with "
                "scope=exploration and connection_to_dossier instead."
            )

    for pattern, label in _OFF_TOPIC_CHECKS:
        if pattern.search(combined) and not pattern.search(stmt_lower):
            errors.append(
                f"Primary proof appears off-topic ({label}). "
                "Either focus on the dossier statement, or record the side thread with "
                "scope=exploration and an explicit connection_to_dossier bridge."
            )

    return errors, warnings


def empty_scaffold(*, theorem: str = "_State the precise theorem or goal._") -> str:
    """Return an empty NL proof skeleton for the agent to fill."""
    return assemble_nl_proof_body(
        theorem=theorem,
        definitions="_Define all symbols and standing assumptions._",
        lemmas="_Optional supporting lemmas, each with a short proof._",
        main_proof="_Write the logical argument step by step. Mark any missing step as [GAP-1], …_",
        gaps_markdown="_List every [GAP-n] and why it remains open._",
        evidence_notes="_Cite EXP-*, PAPER-* here only as corroboration — not as proof._",
    )


def assemble_nl_proof_body(
    *,
    theorem: str = "",
    connection_to_dossier: str = "",
    definitions: str = "",
    lemmas: str = "",
    main_proof: str = "",
    gaps_markdown: str = "",
    evidence_notes: str = "",
    body: str = "",
) -> str:
    """Build markdown body from structured sections or pass through ``body``."""
    if body.strip():
        return body.strip()
    parts: list[str] = []
    if theorem.strip():
        parts.append(f"## Theorem\n\n{theorem.strip()}")
    if connection_to_dossier.strip():
        parts.append(f"## Connection to dossier\n\n{connection_to_dossier.strip()}")
    if definitions.strip():
        parts.append(f"## Definitions\n\n{definitions.strip()}")
    if lemmas.strip():
        parts.append(f"## Lemmas\n\n{lemmas.strip()}")
    if main_proof.strip():
        parts.append(f"## Main proof\n\n{main_proof.strip()}")
    if gaps_markdown.strip():
        parts.append(f"## Gaps and limitations\n\n{gaps_markdown.strip()}")
    if evidence_notes.strip():
        parts.append(f"## Supporting evidence (not proof)\n\n{evidence_notes.strip()}")
    if not parts:
        return empty_scaffold()
    return "\n\n".join(parts) + "\n"


def _gap_marker_key(text: str) -> str | None:
    """Comparable key for a [GAP-n] marker (hyphen/whitespace/case normalized)."""
    match = _GAP_MARKER.search(text)
    if not match:
        return None
    return re.sub(rf"[{_HYPHENS}\s]", "-", match.group(0)).upper()


def explicit_gaps(*, gaps: list[str], body: str) -> list[str]:
    """Merge explicit gap strings with [GAP-n] markers found in the body.

    A gap that appears both as an explicit string (e.g. "[GAP-1] derive bound") and as
    a bare body marker ("[GAP-1]") is counted once: the explicit string already carries
    the marker, so the auto-detected body marker is not appended again. Without this the
    gap count is doubled, which confuses the model and inflates gap-fill budgeting.
    """
    merged = [g.strip() for g in gaps if g.strip()]
    seen = {key for g in merged if (key := _gap_marker_key(g))}
    for marker in sorted(set(_GAP_MARKER.findall(body))):
        key = _gap_marker_key(marker)
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        merged.append(f"Marked in text: {marker}")
    return merged


def bootstrap_proof_write_args(
    problem_id: str,
    goal: str,
    *,
    statement: str = "",
) -> dict:
    """Default tool args when the model must start an NL proof deliverable."""
    title = "Natural-language proof draft"
    if len(goal) <= 80:
        title = goal[0].upper() + goal[1:] if goal else title
    stmt = statement.strip()
    theorem = (
        stmt
        if stmt
        else "_Restate the precise problem from .opentorus/problems/PROBLEM-*/statement.md._"
    )
    return {
        "problem_id": problem_id,
        "title": title,
        "theorem": theorem,
        "definitions": (
            "_Define notation from the dossier statement (e.g. ε_m^*, Π_{2^m}^*, δ, I)._"
        ),
        "lemmas": "",
        "main_proof": (
            "_Status sketch or proof steps about the dossier problem only. "
            "Use [GAP-1] for any unjustified step._"
        ),
        "gaps_markdown": (
            "_List each open gap explicitly; while gaps remain this stays a sketch, "
            "not a settled result._"
        ),
        "evidence_notes": "",
        "gaps": ["Initial scaffold — replace placeholders before marking task done."],
        "kind": "sketch",
    }


_LOG_BOUND = re.compile(
    r"\blog\s*[\(_]?[nd]|\\log|\(n\s*[-−]\s*d\)\s*·?\s*\\?log",
    re.IGNORECASE,
)
_HIRSCH_DIAMETER_CONTEXT = re.compile(
    r"\b(?:hirsch|diameter\s+of\s+(?:the\s+)?(?:graph|polytope)|"
    r"polytop(?:e|al)\s+(?:graph|diameter)|step\s+complexity|facet\s+graph)\b",
    re.IGNORECASE,
)
_RESOLVED_OPEN = re.compile(
    r"\b(?:conjecture\s+holds|therefore,?\s*(?:subject\s+to|the)\s+|"
    r"thus,?\s+the\s+(?:polynomial\s+)?hirsch|we\s+have\s+proved|is\s+proved|"
    r"establish(?:es|ed)\s+the\s+(?:polynomial\s+)?(?:hirsch|conjecture))\b",
    re.IGNORECASE,
)


def lint_proof_sketch(
    body: str,
    *,
    open_problem: bool = False,
    statement: str = "",
    scope: ProofScope = "primary",
    connection_to_dossier: str = "",
) -> list[str]:
    """Heuristic warnings for common NL proof overclaims (not formal verification)."""
    warnings: list[str] = []
    if statement.strip():
        rel_errors, rel_warnings = validate_proof_relevance(
            statement,
            body,
            scope=scope,
            connection_to_dossier=connection_to_dossier,
        )
        if scope == "primary":
            warnings.extend(rel_errors)
        warnings.extend(rel_warnings)
    if open_problem and _RESOLVED_OPEN.search(body):
        warnings.append(
            "Proof sketch appears to resolve an open conjecture — expected a status "
            "survey with explicit [GAP-n], not a claimed proof."
        )
    if (
        _HIRSCH_DIAMETER_CONTEXT.search(body)
        and _LOG_BOUND.search(body)
        and re.search(r"\bpolynomial\b", body, re.IGNORECASE)
    ):
        warnings.append(
            "Text mixes logarithmic bounds with 'polynomial' in a Hirsch/diameter context — "
            "quasi-polynomial bounds do not prove a polynomial Hirsch-type conjecture."
        )
    return warnings
