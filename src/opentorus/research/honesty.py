"""Honesty linter for proof-status discipline (Milestones 52, 63).

Reports and answers must use status-accurate language. Claims of rigor come in
two tiers, each honest only when the matching backing exists:

- **Proof tier** ("proven", "QED", "verified by Z3", "machine-checked"): honest
  only with an accepted formal proof artifact (Milestone 51/62).
- **Bound tier** ("rigorous bound", "rigorous enclosure"): honest with a
  validated-numerics rigorous bound (Milestone 61) *or* a formal proof.

Without the right backing the linter flags the overclaim and suggests
evidence-accurate phrasing, so the agent neither over- nor under-claims.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

# Proof-tier phrases: honest only when a formal proof artifact backs them.
_PROOF_SPECS: list[tuple[str, str]] = [
    (r"\bq\.?e\.?d\.?\b", "drop 'QED'; cite the formal proof artifact"),
    (r"\bproven\b", "say 'supported by evidence' or 'formally verified in <backend>'"),
    (r"\bproved\b", "say 'shown numerically up to N' or cite a proof artifact"),
    (r"\bwe\s+prove\b", "say 'we provide evidence' unless a proof artifact exists"),
    (r"\bthis\s+proves\b", "say 'this supports' unless formally verified"),
    (r"\brigorously\s+established\b", "reserve for formally verified results"),
    (r"\bcertainly\s+true\b", "state the rigor level (conjecture/evidence/verified)"),
    (r"\bverified\s+by\s+(?:z3|cvc5|lean|coq|smt)\b", "cite the accepted PROOF-* artifact"),
    (r"\bmachine[-\s]?checked\b", "reserve for results accepted by a verifier (cite the artifact)"),
]
# Bound-tier phrases: honest with a rigorous bound (M61) or a formal proof.
_BOUND_SPECS: list[tuple[str, str]] = [
    (
        r"\brigorous(?:ly)?\s+(?:bound|enclosure|bounded)\b",
        "call a bound 'rigorous' only with a validated-numerics enclosure (M61)",
    ),
]

_PROOF_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), hint) for pat, hint in _PROOF_SPECS
]
_BOUND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), hint) for pat, hint in _BOUND_SPECS
]


class HonestyIssue(BaseModel):
    """A single overclaim detected in text."""

    line: int
    phrase: str
    suggestion: str


def lint_text(
    text: str,
    *,
    has_formal_proof: bool = False,
    has_rigorous_bound: bool = False,
) -> list[HonestyIssue]:
    """Flag rigor-asserting language unless the matching backing exists.

    ``has_formal_proof`` licenses both proof- and bound-tier language (a verifier
    accepted the result); ``has_rigorous_bound`` licenses only the bound tier (a
    validated-numerics enclosure, M61).
    """
    active: list[tuple[re.Pattern[str], str]] = []
    if not has_formal_proof:
        active.extend(_PROOF_PATTERNS)
        if not has_rigorous_bound:
            active.extend(_BOUND_PATTERNS)
    issues: list[HonestyIssue] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        for pattern, suggestion in active:
            match = pattern.search(raw)
            if match:
                issues.append(
                    HonestyIssue(line=lineno, phrase=match.group(0), suggestion=suggestion)
                )
    return issues


def is_honest(
    text: str, *, has_formal_proof: bool = False, has_rigorous_bound: bool = False
) -> bool:
    """True if ``text`` contains no unbacked rigor claims."""
    return not lint_text(
        text, has_formal_proof=has_formal_proof, has_rigorous_bound=has_rigorous_bound
    )
