"""Artifact-aware honesty linter for dossier reports (Milestone M1, Phase 3).

The linter does not blindly ban words. It classifies a flagged phrase and checks
whether the dossier actually has the artifacts that would make the phrase honest:

* **Proof claims** ("we prove", "this proves", "QED", "establishes the theorem",
  "solves the problem", "therefore the conjecture is true") are honest only with
  a verified proof artifact.
* **Knowledge claims** ("it is known that", "known that") are honest only with a
  reference artifact (a paper, theorem reference, or REFERENCE_FACT claim).
* **Experiment-as-proof claims** ("the experiment proves", "numerically proves")
  are *always* rejected — evidence never proves.
* **Weasel words** ("obvious", "trivial", "clearly follows") are always flagged
  as needing justification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class IssueKind(StrEnum):
    PROOF_CLAIM = "proof_claim"
    KNOWLEDGE_CLAIM = "knowledge_claim"
    EXPERIMENT_PROOF = "experiment_proof"
    RESULT_CLAIM = "result_claim"
    WEASEL = "weasel"


@dataclass(frozen=True)
class ReportIssue:
    line: int
    phrase: str
    kind: IssueKind
    suggestion: str


# Experiment-as-proof: always wrong, checked first so it wins over generic "prove".
_EXPERIMENT_PROOF = re.compile(
    r"\b(?:experiments?|simulations?|numerics?|computations?|tests?)\b[^.]{0,40}?\b"
    r"prov(?:e|es|ed|en)\b",
    re.IGNORECASE,
)
_NUMERICALLY_PROVEN = re.compile(r"\bnumerically\s+prov(?:e|es|ed|en)\b", re.IGNORECASE)

_PROOF_CLAIM = re.compile(
    r"\b(?:we\s+prove|this\s+proves|it\s+is\s+proven|is\s+proven|q\.?e\.?d\.?|"
    r"establishes?\s+the\s+theorem|solves?\s+the\s+(?:problem|conjecture)|"
    r"therefore\s+the\s+conjecture\s+is\s+true|proves?\s+the\s+conjecture|"
    r"hence\s+proven)\b",
    re.IGNORECASE,
)

# Result-assertion language ("provably", "we proved", "this establishes", "the
# problem is solved", "therefore the theorem holds"). These assert a *settled*
# result and so are honest only when the dossier actually carries a supported (or
# stronger) THEOREM. Phrasing is deliberately specific so the generated, honest
# report (which says "open", "conjecture", "supported", "solved externally")
# never trips it. A leading "not"/"to be" disclaimer is honest hedging.
_RESULT_CLAIM = re.compile(
    r"\b(?:"
    r"provably"
    r"|this\s+establishes"
    r"|we\s+(?:have\s+)?(?:proved|established)"
    r"|(?<!not\s)(?<!to\s)(?:be\s+|been\s+|is\s+|are\s+|was\s+|were\s+)(?:proved|established)"
    r"|(?:problem|conjecture)\s+is\s+(?:now\s+)?solved"
    r"|therefore\s+(?:the\s+)?(?:theorem|result|claim|conjecture|statement|bound)"
    r"\s+(?:is\s+|are\s+)?(?:proved|proven|holds?|follows?|established)"
    r")\b",
    re.IGNORECASE,
)

# Affirmative knowledge claims only: an explicit disclaimer ("it is not known
# that ...") is honest hedging, not an overclaim, so a "not"/"un-" before the
# phrase must not trip the linter.
_KNOWLEDGE_CLAIM = re.compile(
    r"\b(?:it\s+is\s+known\s+that|(?<!not\s)(?<!un)known\s+that|(?<!not\s)well[-\s]known)\b",
    re.IGNORECASE,
)

_WEASEL = re.compile(
    r"\b(?:obvious(?:ly)?|trivial(?:ly)?|clearly\s+follows|clearly|evidently)\b", re.IGNORECASE
)


def lint_report(
    text: str,
    *,
    has_verified_proof: bool = False,
    has_reference: bool = False,
    has_supported_theorem: bool = False,
) -> list[ReportIssue]:
    """Flag overclaims that the dossier's artifacts do not justify.

    ``has_supported_theorem`` licenses *result-assertion* language ("provably",
    "we proved", "the problem is solved"): such language is honest only when the
    dossier carries at least one supported (or stronger) THEOREM. A verified proof
    artifact additionally licenses the stronger proof-claim phrases.
    """
    from opentorus.textnorm import normalize_for_scan

    issues: list[ReportIssue] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        # Fold zero-width splits / homoglyphs so evasions cannot slip an overclaim past.
        line = normalize_for_scan(raw).strip()
        if not line:
            continue
        # Lint heading *text* too: an overclaim in "# We prove the conjecture" must
        # not get a free pass just for being a heading. Strip the leading markers.
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if not line:
                continue

        if _EXPERIMENT_PROOF.search(line) or _NUMERICALLY_PROVEN.search(line):
            m = _EXPERIMENT_PROOF.search(line) or _NUMERICALLY_PROVEN.search(line)
            assert m is not None
            issues.append(
                ReportIssue(
                    line=lineno,
                    phrase=m.group(0),
                    kind=IssueKind.EXPERIMENT_PROOF,
                    suggestion=(
                        "Experiments never prove. Say 'the experiment supports' and cite "
                        "the EXP-* manifest."
                    ),
                )
            )
            continue

        if (m := _PROOF_CLAIM.search(line)) and not has_verified_proof:
            issues.append(
                ReportIssue(
                    line=lineno,
                    phrase=m.group(0),
                    kind=IssueKind.PROOF_CLAIM,
                    suggestion=(
                        "No verified proof artifact in this dossier. Say 'we provide "
                        "evidence' / 'proof sketch (not checked)' unless a verifier "
                        "accepted the proof."
                    ),
                )
            )

        if (m := _RESULT_CLAIM.search(line)) and not has_supported_theorem:
            issues.append(
                ReportIssue(
                    line=lineno,
                    phrase=m.group(0),
                    kind=IssueKind.RESULT_CLAIM,
                    suggestion=(
                        "No supported THEOREM backs this result-assertion. Use "
                        "'we conjecture' / 'the evidence suggests' / 'a sketch argues', "
                        "or record a supported THEOREM first."
                    ),
                )
            )

        if (m := _KNOWLEDGE_CLAIM.search(line)) and not has_reference:
            issues.append(
                ReportIssue(
                    line=lineno,
                    phrase=m.group(0),
                    kind=IssueKind.KNOWLEDGE_CLAIM,
                    suggestion=(
                        "Cite a local source (PAPER-*, theorem reference, or "
                        "REFERENCE_FACT claim) before calling something 'known'."
                    ),
                )
            )

        if m := _WEASEL.search(line):
            issues.append(
                ReportIssue(
                    line=lineno,
                    phrase=m.group(0),
                    kind=IssueKind.WEASEL,
                    suggestion="Replace with an explicit justification or a cited step.",
                )
            )
    return issues


def is_honest(
    text: str,
    *,
    has_verified_proof: bool = False,
    has_reference: bool = False,
    has_supported_theorem: bool = False,
) -> bool:
    return not lint_report(
        text,
        has_verified_proof=has_verified_proof,
        has_reference=has_reference,
        has_supported_theorem=has_supported_theorem,
    )
