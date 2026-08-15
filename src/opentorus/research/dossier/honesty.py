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
    NOT_BUILT = "not_built"


@dataclass(frozen=True)
class ReportIssue:
    line: int
    phrase: str
    kind: IssueKind
    suggestion: str


# Experiment-as-proof: always wrong, checked first so it wins over generic "prove".
# The gap between the experiment word and "prove" must not cross a negation:
# "experiments support X but do not prove it" is exactly the honest phrasing this
# linter asks for, and flagging it taught the model nothing it could fix.
_EXPERIMENT_PROOF = re.compile(
    r"\b(?:experiments?|simulations?|numerics?|computations?|tests?)\b"
    r"(?:(?!\b(?:not|never|cannot|can'?t|don'?t|doesn'?t|didn'?t|fails?\s+to)\b)[^.]){0,40}?"
    r"\bprov(?:e|es|ed|en)\b",
    re.IGNORECASE,
)
_NUMERICALLY_PROVEN = re.compile(
    r"(?<!\bnot\s)(?<!\bnever\s)(?<!\bto\s)\bnumerically\s+prov(?:e|es|ed|en)\b", re.IGNORECASE
)

# "fail to prove / cannot prove / does not prove the conjecture" is honest
# hedging, not a proof claim — hence the lookbehinds on the bare-verb branch.
_PROOF_CLAIM = re.compile(
    r"\b(?:we\s+prove|this\s+proves|it\s+is\s+proven|(?<!not\s)is\s+proven|q\.?e\.?d\.?|"
    r"establishes?\s+the\s+theorem|solves?\s+the\s+(?:problem|conjecture)|"
    r"therefore\s+the\s+conjecture\s+is\s+true|"
    r"(?<!to\s)(?<!not\s)(?<!cannot\s)(?<!never\s)proves?\s+the\s+conjecture|"
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

# "trivial" as a *classifier noun phrase* ("the trivial family/solution (X-a)^d")
# names a mathematical object; only adverbial/dismissive uses ("trivially",
# "the proof is trivial") wave a justification away.
_WEASEL = re.compile(
    r"\b(?:obvious(?:ly)?"
    r"|trivial(?!\s+(?:family|solutions?|zeros?|kernel|ideal|subgroup|representation)\b)(?:ly)?"
    r"|clearly\s+follows|clearly|evidently)\b",
    re.IGNORECASE,
)

# A local paper citation on the same line attributes a passive result-assertion
# ("... is proved for d = p^k; PAPER-0004 Theorem 3") to that source — the
# citation-grounding check separately validates the theorem number, so flagging
# it here punished honest literature reporting. First-person and "provably"
# claims stay flagged: citing a paper does not launder one's own assertion.
_PAPER_REF = re.compile(r"\bPAPER-\d{4}\b", re.IGNORECASE)

# Referee findings quote the offending phrase ("[REFEREE] ... 'is proved' ...");
# re-flagging the quotation inside the finding loops the linter on its own
# output. On such lines only the text OUTSIDE single-quoted spans is linted, so
# an overclaim smuggled outside the quotes still trips.
_REFEREE_QUOTE = re.compile(r"'[^']*'")


def _strip_referee_quotes(line: str) -> str:
    stripped = line.lstrip("-*• \t")
    if stripped.startswith("[REFEREE]"):
        return _REFEREE_QUOTE.sub("''", stripped)
    return line


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
    in_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        # Fold zero-width splits / homoglyphs so evasions cannot slip an overclaim past.
        line = normalize_for_scan(raw).strip()
        if not line:
            continue
        # Fenced code blocks are verbatim material — a Coq template's `Qed.` or a
        # script snippet is not an assertion by the report. A reader sees code
        # formatting, not a claim. Inline `code` spans stay linted, so prose
        # overclaims cannot hide behind a pair of backticks.
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = _strip_referee_quotes(line)
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
            # Same attribution rule as result-claims below: "Barajas-Serra prove the
            # conjecture for k=6; PAPER-0001 p.2" reports a cited literature result.
            # Self-claims (we/this/it is/QED/hence/therefore) stay flagged regardless.
            attributed = _PAPER_REF.search(line) is not None and not m.group(0).lower().startswith(
                ("we", "this", "it is", "q", "hence", "therefore")
            )
            if not attributed:
                issues.append(
                    ReportIssue(
                        line=lineno,
                        phrase=m.group(0),
                        kind=IssueKind.PROOF_CLAIM,
                        suggestion=(
                            "No verified proof artifact in this dossier. Say 'we provide "
                            "evidence' / 'proof sketch (not checked)' unless a verifier "
                            "accepted the proof, or cite the PAPER-* that proves it on "
                            "the same line."
                        ),
                    )
                )

        if (m := _RESULT_CLAIM.search(line)) and not has_supported_theorem:
            attributed = _PAPER_REF.search(line) is not None and not m.group(0).lower().startswith(
                ("we", "this", "provably")
            )
            if not attributed:
                issues.append(
                    ReportIssue(
                        line=lineno,
                        phrase=m.group(0),
                        kind=IssueKind.RESULT_CLAIM,
                        suggestion=(
                            "No supported THEOREM backs this result-assertion. Use "
                            "'we conjecture' / 'the evidence suggests' / 'a sketch argues', "
                            "cite the PAPER-* that proves it on the same line, "
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
