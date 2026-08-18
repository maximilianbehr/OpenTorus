"""Deterministic applicability checks: does a theorem reference apply to a claim?

The check is a fixed, ordered list of shallow, explainable tests over the stored
reference, the local source and the caller's assumption context. Each test is
recorded as a :class:`CheckItem`; the typed ``result`` follows the precedence
``rejected > needs-human-review > inconclusive > accepted``. The checker is
intentionally conservative — text heuristics can *refuse* or *defer* to a human,
but an ``accepted`` here is still only a recorded check: it never changes any
claim status (the verifier-coordinator may cite it; promotion needs a
verification artifact, as everywhere else in the dossier).

A model may attach ``proposed_analysis`` (prose) to the record; it is stored
verbatim and has no influence on the result.
"""

from __future__ import annotations

import re
from pathlib import Path

from opentorus.research.theorems import store
from opentorus.research.theorems.locators import located_context, location_hash, validate_locator
from opentorus.research.theorems.models import (
    ApplicabilityCheck,
    ApplicabilityResult,
    CheckItem,
    Direction,
    TheoremReference,
    TheoremRelationKind,
)
from opentorus.research.theorems.relations import contradicting_refs

# Glue words removed before token comparison; quantifier words are removed here
# because quantifier agreement is a separate check.
_STOPWORDS = frozenset(
    "the a an and or of to in for on with that this is are be as it its let suppose assume "
    "if then we have such so given any all every each some there exists exist by from at "
    "which can not no than thus hence where when holds hold".split()
)
_UNIVERSAL_WORDS = re.compile(r"\b(?:for\s+(?:all|every|each|any)|every|all|each)\b", re.I)
_EXISTENTIAL_WORDS = re.compile(
    r"\b(?:there\s+(?:exist|exists|is\s+(?:a|an|some))|for\s+some|exists?|some)\b", re.I
)
# Domain/parameter vocabulary whose presence in a hypothesis is load-bearing. A
# hypothesis token that the context neither states nor contradicts is a mismatch.
_DOMAIN_TOKENS = (
    "finite",
    "infinite",
    "compact",
    "smooth",
    "real",
    "complex",
    "prime",
    "integer",
    "bounded",
    "unbounded",
    "connected",
    "convex",
)
_ANTONYMS = {
    "finite": "infinite",
    "infinite": "finite",
    "real": "complex",
    "complex": "real",
    "bounded": "unbounded",
    "unbounded": "bounded",
}
_PARAMETER = re.compile(r"\b([dnkmp])\s*(=|>=|<=|>|<)\s*(\d+)\b", re.I)
_THMREF_ID = re.compile(r"^THMREF-\d+$", re.I)

HYPOTHESIS_JACCARD = 0.6
CONCLUSION_OVERLAP = 0.3


def normalize_text(text: str) -> str:
    """Lowercase, punctuation stripped, whitespace collapsed."""
    return " ".join(re.sub(r"[^a-z0-9=<>\s]", " ", text.lower()).split())


def tokens(text: str) -> set[str]:
    return {t for t in normalize_text(text).split() if t not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _hypothesis_covered(hypothesis: str, context: list[str]) -> str | None:
    """The context sentence covering ``hypothesis`` (substring or Jaccard), else None."""
    h_norm = normalize_text(hypothesis)
    h_tok = tokens(hypothesis)
    for sentence in context:
        s_norm = normalize_text(sentence)
        if h_norm and (h_norm in s_norm or s_norm in h_norm):
            return sentence
        if jaccard(h_tok, tokens(sentence)) >= HYPOTHESIS_JACCARD:
            return sentence
    return None


def _quantifier_shape(text: str) -> tuple[bool, bool]:
    return bool(_UNIVERSAL_WORDS.search(text)), bool(_EXISTENTIAL_WORDS.search(text))


def _domain_mismatches(hypotheses_text: str, context_text: str) -> list[str]:
    """Named domain/parameter tokens the hypotheses need but the context lacks or negates."""
    hyp = tokens(hypotheses_text)
    ctx = tokens(context_text)
    mismatches: list[str] = []
    for word in _DOMAIN_TOKENS:
        if word not in hyp:
            continue
        antonym = _ANTONYMS.get(word)
        if antonym and antonym in ctx and word not in ctx:
            mismatches.append(
                f"'{word}' required by the hypotheses but the context says '{antonym}'"
            )
        elif word not in ctx:
            mismatches.append(f"'{word}' required by the hypotheses but absent from the context")
    ctx_params = {
        (m.group(1).lower(), m.group(2)): m.group(3)
        for m in _PARAMETER.finditer(normalize_text(context_text))
    }
    for m in _PARAMETER.finditer(normalize_text(hypotheses_text)):
        key = (m.group(1).lower(), m.group(2))
        wanted = m.group(3)
        found = ctx_params.get(key)
        if found is None:
            mismatches.append(
                f"parameter '{key[0]} {key[1]} {wanted}' required by the hypotheses but "
                "absent from the context"
            )
        elif found != wanted:
            mismatches.append(
                f"parameter '{key[0]} {key[1]} {wanted}' required by the hypotheses but the "
                f"context has '{key[0]} {key[1]} {found}'"
            )
    return mismatches


def _relations_covering(ot_dir: Path, ref: TheoremReference, context_refs: list[str]) -> bool:
    """A context reference declares ``implies``/``requires-definition`` towards ``ref``."""
    if not context_refs:
        return False
    wanted = {r.upper() for r in context_refs}
    for rel in store.list_relations(ot_dir, ref_id=ref.id):
        if rel.review_status == "rejected":
            continue
        if rel.relation in (
            TheoremRelationKind.implies,
            TheoremRelationKind.requires_definition,
        ) and (rel.target_ref.upper() == ref.id.upper() and rel.source_ref.upper() in wanted):
            return True
    return False


def _has_equivalence(ot_dir: Path, ref: TheoremReference) -> bool:
    return any(
        rel.relation is TheoremRelationKind.equivalent_to and rel.review_status != "rejected"
        for rel in store.list_relations(ot_dir, ref_id=ref.id)
    )


def check_applicability(
    ot_dir: Path,
    ref_id: str,
    *,
    problem_id: str,
    assumption_context: list[str],
    claim_text: str,
    direction: Direction = "forward",
    target_id: str | None = None,
    proposed_analysis: str | None = None,
) -> ApplicabilityCheck:
    """Run the ordered deterministic checks and persist the typed result.

    ``assumption_context`` entries may be plain sentences or THMREF ids; the
    latter count as "context references" whose declared relations can cover a
    hypothesis. Never touches claim status.
    """
    from opentorus.research.papers import get_paper

    ref = store.require_reference(ot_dir, ref_id)
    checks: list[CheckItem] = []
    mismatches: list[str] = []
    verdicts: set[ApplicabilityResult] = set()
    context_sentences = [c for c in assumption_context if not _THMREF_ID.match(c.strip())]
    context_refs = [c.strip().upper() for c in assumption_context if _THMREF_ID.match(c.strip())]

    # 1. paper exists
    if get_paper(ot_dir, ref.paper_id) is None:
        checks.append(
            CheckItem(name="paper_exists", passed=False, detail=f"no local {ref.paper_id}")
        )
        verdicts.add(ApplicabilityResult.rejected)
        mismatches.append(f"paper {ref.paper_id} is not a local artifact")
    else:
        checks.append(CheckItem(name="paper_exists", passed=True, detail=ref.paper_id))

    # 2. locator resolves
    validation = validate_locator(ot_dir, ref.locator)
    if validation.ok:
        detail = "; ".join(validation.warnings) or "ok"
        checks.append(CheckItem(name="locator_resolves", passed=True, detail=detail))
    else:
        checks.append(
            CheckItem(name="locator_resolves", passed=False, detail="; ".join(validation.errors))
        )
        verdicts.add(ApplicabilityResult.rejected)
        mismatches.extend(validation.errors)

    # 3. statement observed (context found and hash unchanged since extraction)
    context = located_context(ot_dir, ref.locator)
    if context is None:
        checks.append(
            CheckItem(
                name="statement_observed",
                passed=None,
                detail="statement not locatable in the parsed corpus",
            )
        )
        verdicts.add(ApplicabilityResult.inconclusive)
    elif not ref.location_hash:
        checks.append(
            CheckItem(name="statement_observed", passed=None, detail="no location hash stored")
        )
        verdicts.add(ApplicabilityResult.inconclusive)
    elif location_hash(context) != ref.location_hash:
        checks.append(
            CheckItem(
                name="statement_observed",
                passed=False,
                detail="source text changed since extraction",
            )
        )
        verdicts.add(ApplicabilityResult.inconclusive)
        mismatches.append("source text changed since extraction; re-extract and re-review")
    else:
        checks.append(CheckItem(name="statement_observed", passed=True, detail="hash matches"))

    # 4. hypotheses represented
    if not ref.assumptions:
        checks.append(
            CheckItem(
                name="hypotheses_represented",
                passed=False,
                detail="reference records no hypotheses; nothing to check against",
            )
        )
        verdicts.add(ApplicabilityResult.inconclusive)
    else:
        checks.append(
            CheckItem(
                name="hypotheses_represented",
                passed=True,
                detail=f"{len(ref.assumptions)} hypothesis(es)",
            )
        )

    # 5. assumption context implies hypotheses
    if ref.assumptions:
        uncovered: list[str] = []
        covered_by_relation = _relations_covering(ot_dir, ref, context_refs)
        for hyp in ref.assumptions:
            if _hypothesis_covered(hyp, context_sentences) is None and not covered_by_relation:
                uncovered.append(hyp)
        if uncovered:
            checks.append(
                CheckItem(
                    name="context_implies_hypotheses",
                    passed=False,
                    detail="uncovered: " + " | ".join(uncovered),
                )
            )
            verdicts.add(ApplicabilityResult.needs_human_review)
        else:
            checks.append(
                CheckItem(name="context_implies_hypotheses", passed=True, detail="all covered")
            )
    else:
        checks.append(
            CheckItem(name="context_implies_hypotheses", passed=None, detail="no hypotheses")
        )

    # 6. conclusion supports claim
    conclusion_tokens = tokens(ref.conclusion)
    if not conclusion_tokens or not claim_text.strip():
        checks.append(
            CheckItem(
                name="conclusion_supports_claim",
                passed=None,
                detail="no conclusion recorded" if not conclusion_tokens else "no claim text",
            )
        )
        verdicts.add(ApplicabilityResult.inconclusive)
    else:
        overlap = len(conclusion_tokens & tokens(claim_text)) / len(conclusion_tokens)
        if overlap >= CONCLUSION_OVERLAP:
            checks.append(
                CheckItem(
                    name="conclusion_supports_claim", passed=True, detail=f"overlap {overlap:.2f}"
                )
            )
        else:
            checks.append(
                CheckItem(
                    name="conclusion_supports_claim",
                    passed=False,
                    detail=f"overlap {overlap:.2f} < {CONCLUSION_OVERLAP}",
                )
            )
            verdicts.add(ApplicabilityResult.inconclusive)

    # 7. direction
    if direction == "converse":
        if _has_equivalence(ot_dir, ref):
            checks.append(
                CheckItem(
                    name="direction", passed=True, detail="converse licensed by equivalent-to"
                )
            )
        else:
            checks.append(
                CheckItem(
                    name="direction",
                    passed=False,
                    detail="converse requested but only the forward implication is recorded",
                )
            )
            verdicts.add(ApplicabilityResult.rejected)
            mismatches.append("converse direction is not licensed by any equivalent-to relation")
    else:
        checks.append(CheckItem(name="direction", passed=True, detail="forward"))

    # 8. quantifier agreement
    ref_text = " ".join(ref.quantifiers) + " " + ref.normalized_statement
    ref_u, ref_e = _quantifier_shape(ref_text)
    claim_u, claim_e = _quantifier_shape(claim_text)
    if (ref_u or ref_e) and (claim_u or claim_e):
        if (ref_u and not ref_e and claim_e and not claim_u) or (
            ref_e and not ref_u and claim_u and not claim_e
        ):
            shape_ref = "universal" if ref_u else "existential"
            shape_claim = "universal" if claim_u else "existential"
            checks.append(
                CheckItem(
                    name="quantifier_agreement",
                    passed=False,
                    detail=f"theorem is {shape_ref}, claim is {shape_claim}",
                )
            )
            verdicts.add(ApplicabilityResult.rejected)
            mismatches.append(f"quantifier mismatch: theorem {shape_ref} vs claim {shape_claim}")
        else:
            checks.append(CheckItem(name="quantifier_agreement", passed=True, detail="compatible"))
    else:
        checks.append(
            CheckItem(name="quantifier_agreement", passed=None, detail="no quantifier words")
        )

    # 9. domain / parameter agreement (context = assumptions + claim text)
    domain = _domain_mismatches(
        " ".join(ref.assumptions), " ".join(context_sentences + [claim_text])
    )
    if domain:
        checks.append(CheckItem(name="domain_agreement", passed=False, detail="; ".join(domain)))
        verdicts.add(ApplicabilityResult.rejected)
        mismatches.extend(domain)
    else:
        checks.append(CheckItem(name="domain_agreement", passed=True, detail="no domain conflict"))

    # 10. contradicted / superseded by an accepted reference
    accepted_contradictions = [
        other
        for other in contradicting_refs(ot_dir, ref.id)
        if (found := store.get_reference(ot_dir, other)) is not None
        and found.review_status == "accepted"
    ]
    if accepted_contradictions:
        checks.append(
            CheckItem(
                name="not_contradicted",
                passed=False,
                detail="contradicted by accepted " + ", ".join(accepted_contradictions),
            )
        )
        verdicts.add(ApplicabilityResult.rejected)
        mismatches.append("contradicted by accepted " + ", ".join(accepted_contradictions))
    else:
        checks.append(CheckItem(name="not_contradicted", passed=True, detail="none"))

    if ApplicabilityResult.rejected in verdicts:
        result = ApplicabilityResult.rejected
    elif ApplicabilityResult.needs_human_review in verdicts:
        result = ApplicabilityResult.needs_human_review
    elif ApplicabilityResult.inconclusive in verdicts:
        result = ApplicabilityResult.inconclusive
    else:
        result = ApplicabilityResult.accepted

    return store.add_applicability_check(
        ot_dir,
        ApplicabilityCheck(
            theorem_reference_id=ref.id,
            problem_id=problem_id.strip().upper(),
            target_id=target_id,
            assumption_context=list(assumption_context),
            claim_text=claim_text,
            direction=direction,
            result=result,
            checks=checks,
            mismatches=mismatches,
            performed_by="deterministic",
            proposed_analysis=proposed_analysis,
        ),
    )
