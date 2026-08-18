"""Extract *candidate* theorem references from a locally parsed paper.

Two extractors, one contract: every reference produced here is
``review_status="candidate"``, located (label found in the corpus, context hashed)
and excerpted from the source. The heuristic extractor is deterministic and
offline; the LLM extractor asks a model for structure but still validates each
proposed locator against the local corpus and never trusts a label the corpus
does not contain. Neither can promote a reference — that is ``theorem review``.

Every candidate also carries *category hints* (:func:`infer_categories`): a coverage
category read off the label family and the statement's own vocabulary, so a
candidate shows up as ``partial`` coverage of that category instead of no coverage
at all. A hint is never more than a hint — ``adequate`` needs review, and review
replaces the hints with a human classification.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opentorus.errors import OpenTorusError
from opentorus.research.paper_citations import _THM_LABEL, paper_corpus
from opentorus.research.theorems import store
from opentorus.research.theorems.locators import (
    _body_offset,
    clip_excerpt,
    context_at,
    find_label,
    located_context,
    location_hash,
    parse_label,
    validate_locator,
)
from opentorus.research.theorems.models import (
    CoverageCategory,
    ExtractionMethod,
    SourceLocator,
    TheoremReference,
)

if TYPE_CHECKING:
    from opentorus.config import Config
    from opentorus.providers.base import BaseProvider
    from opentorus.providers.pool import ProviderLease, ProviderPool

logger = logging.getLogger("opentorus")

# Only statement-bearing environments become references; definitions/remarks/
# equations/examples are citable in proofs but are not "results".
_STATEMENT_FAMILIES = frozenset({"theorem", "lemma", "proposition", "corollary"})
_CONTEXT_WIDTH = 400
_LLM_MAX_CHARS = 24_000

# Sentence split: end punctuation followed by whitespace and an uppercase/opening
# character. Result numbers ("2.1") have no whitespace after the dot, so they survive.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
_HYPOTHESIS_LEAD = re.compile(r"^(?:let|suppose|assume|if)\b", re.I)
_UNIVERSAL = re.compile(r"\b((?:for\s+)?(?:all|every|each|any)\b[^,.;:]{0,60})", re.I)
_EXISTENTIAL = re.compile(
    r"\b((?:there\s+(?:exist|exists|is|are)|for\s+some|exists)\b[^,.;:]{0,60})", re.I
)
_CONCLUSION_LEAD = re.compile(
    r"\b(?:then|we\s+have(?:\s+that)?|it\s+follows(?:\s+that)?)\b\s*[:,]?\s*", re.I
)
_TITLE_AFTER_LABEL = re.compile(r"^\s*\(([^)]{1,120})\)")

# Category hints. A statement that names a counterexample, or whose conclusion is a
# non-existence / failure, is filed under the negative categories; every other
# Theorem / Corollary is a known positive result of the local literature and a Lemma /
# Proposition is a tool. Deliberately shallow: the hint decides which coverage row a
# candidate appears in (at most ``partial``), nothing about the root problem.
_COUNTEREXAMPLE_HINT = re.compile(r"\bcounter-?examples?\b", re.I)
_NEGATIVE_HINT = re.compile(
    r"\b(?:there\s+(?:is|are|exists?)\s+no\b|does\s+not\s+(?:hold|exist|admit|have)\b|"
    r"do\s+not\s+(?:hold|exist|admit|have)\b|cannot\b|fails?\s+(?:to|for)\b|"
    r"is\s+(?:false|not\s+true)\b|impossible\b|no\s+such\b)",
    re.I,
)
_TOOL_FAMILIES = frozenset({"lemma", "proposition"})


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def parse_statement(context: str, label: str) -> dict[str, Any]:
    """Heuristic structure of a theorem statement that starts with ``label``.

    Returns ``title`` (parenthesised name after the label), ``statement`` (the
    text after the label), ``assumptions`` (sentences opening with Let/Suppose/
    Assume/If, with an ``If ..., then`` split), ``quantifiers`` (matched
    universal/existential phrases) and ``conclusion`` (text after then/we have/it
    follows, else the last non-hypothesis sentence). Deterministic and shallow by
    design: it produces a *candidate* a human reviews, not a parse to trust.
    """
    keyword, number = parse_label(label)
    body = context
    m = re.match(
        rf"\s*{re.escape(keyword) if keyword else ''}\s*{re.escape(number or '')}\s*",
        body,
        re.I,
    )
    if m is not None and m.end() > 0:
        body = body[m.end() :]
    title = ""
    tm = _TITLE_AFTER_LABEL.match(body)
    if tm is not None:
        title = tm.group(1).strip()
        body = body[tm.end() :]
    body = body.lstrip(" .:").strip()

    assumptions: list[str] = []
    conclusion = ""
    others: list[str] = []
    for sentence in _split_sentences(body):
        if _HYPOTHESIS_LEAD.match(sentence):
            if sentence.lower().startswith("if"):
                parts = re.split(r",\s*then\b\s*", sentence, maxsplit=1, flags=re.I)
                if len(parts) == 2:
                    assumptions.append(parts[0].strip().rstrip(",") + ".")
                    if not conclusion:
                        conclusion = parts[1].strip()
                    continue
            assumptions.append(sentence)
        else:
            others.append(sentence)
    if not conclusion:
        cm = _CONCLUSION_LEAD.search(body)
        if cm is not None:
            tail = body[cm.end() :].strip()
            conclusion = _split_sentences(tail)[0] if tail else ""
    if not conclusion and others:
        conclusion = others[-1]

    quantifiers: list[str] = []
    for regex in (_UNIVERSAL, _EXISTENTIAL):
        for qm in regex.finditer(body):
            phrase = " ".join(qm.group(1).split())
            if phrase.lower() not in {q.lower() for q in quantifiers}:
                quantifiers.append(phrase)

    return {
        "title": title,
        "statement": " ".join(body.split()),
        "assumptions": assumptions,
        "quantifiers": quantifiers,
        "conclusion": conclusion,
    }


def infer_categories(label: str, statement: str = "") -> list[CoverageCategory]:
    """Coverage category hints for a candidate with ``label`` and ``statement`` text.

    ``Lemma`` / ``Proposition`` -> ``standard_tools_lemmas``; ``Theorem`` /
    ``Corollary`` -> ``known_counterexamples`` when the statement names a
    counterexample, ``known_negative_results`` when it states a non-existence or a
    failure, else ``strongest_known_positive_results``. Pure and deterministic; the
    result is what makes a candidate count as *partial* coverage of that category.
    """
    keyword, _number = parse_label(label)
    family = (keyword or "").lower()
    if family in _TOOL_FAMILIES:
        return [CoverageCategory.standard_tools_lemmas]
    text = statement or ""
    if _COUNTEREXAMPLE_HINT.search(text):
        return [CoverageCategory.known_counterexamples]
    if _NEGATIVE_HINT.search(text):
        return [CoverageCategory.known_negative_results]
    return [CoverageCategory.strongest_known_positive_results]


def _build_reference(
    *,
    paper_id: str,
    label: str,
    context: str,
    problem_id: str | None,
    extraction_method: ExtractionMethod,
    source_path: str | None,
    page: int | None = None,
    section: str | None = None,
    llm_fields: dict[str, Any] | None = None,
) -> TheoremReference:
    parsed = parse_statement(context, label) if context else {}
    llm = llm_fields or {}
    statement = str(llm.get("statement") or parsed.get("statement") or "")
    return TheoremReference(
        paper_id=paper_id,
        locator=SourceLocator(
            paper_id=paper_id, label=label, page=page, section=section, source_path=source_path
        ),
        theorem_label=label,
        title=str(llm.get("title") or parsed.get("title") or ""),
        location_hash=location_hash(context) if context else "",
        excerpt=clip_excerpt(context) if context else "",
        normalized_statement=statement,
        assumptions=list(llm.get("assumptions") or parsed.get("assumptions") or []),
        quantifiers=list(llm.get("quantifiers") or parsed.get("quantifiers") or []),
        conclusion=str(llm.get("conclusion") or parsed.get("conclusion") or ""),
        problem_id=problem_id,
        categories=infer_categories(label, statement),
        extraction_method=extraction_method,
        extracting_model=llm.get("extracting_model"),
        routing_decision_id=llm.get("routing_decision_id"),
        review_status="candidate",
    )


def _require_corpus(ot_dir: Path, paper_id: str) -> tuple[str, str, str | None]:
    """``(paper_id, raw corpus, text_path)`` or an OpenTorusError explaining why not."""
    from opentorus.research.papers import get_paper

    pid = paper_id.strip().upper()
    paper = get_paper(ot_dir, pid)
    if paper is None:
        raise OpenTorusError(f"No paper with id '{pid}'.")
    corpus = paper_corpus(ot_dir, pid, lower=False)
    if corpus is None:
        raise OpenTorusError(
            f"{pid} has no parsed full text; run `opentorus paper read-unread` (or paper "
            "fetch) first — theorem references are only extracted from local text."
        )
    return pid, corpus, paper.text_path


def discover_labels(corpus: str) -> list[str]:
    """Statement labels ("Theorem 2.1", ...) present in the corpus, in first-seen order.

    Only Theorem/Lemma/Proposition/Corollary families; each (family, number) once.
    """
    seen: set[tuple[str, str]] = set()
    labels: list[str] = []
    for m in _THM_LABEL.finditer(corpus):
        family = m.group(1).lower()
        if family not in _STATEMENT_FAMILIES:
            continue
        key = (family, m.group(2))
        if key in seen:
            continue
        seen.add(key)
        labels.append(f"{family.capitalize()} {m.group(2)}")
    return labels


def extract_heuristic(
    ot_dir: Path, paper_id: str, *, problem_id: str | None = None
) -> list[TheoremReference]:
    """Create candidate references for every numbered result found in the corpus.

    Skips labels that already have a reference for this paper (dedupe by
    ``(paper_id, label)``), so re-running is idempotent.
    """
    pid, corpus, text_path = _require_corpus(ot_dir, paper_id)
    existing = {
        (r.theorem_label or "").lower() for r in store.list_references(ot_dir, paper_id=pid)
    }
    body_offset = _body_offset(ot_dir, pid, corpus)
    created: list[TheoremReference] = []
    for label in discover_labels(corpus):
        if label.lower() in existing:
            continue
        keyword, number = parse_label(label)
        if number is None:
            continue
        match = find_label(corpus, keyword, number, body_offset=body_offset)
        if match is None:
            continue
        context = context_at(corpus, match.start(), width=_CONTEXT_WIDTH)
        ref = _build_reference(
            paper_id=pid,
            label=label,
            context=context,
            problem_id=problem_id,
            extraction_method="heuristic",
            source_path=text_path,
        )
        created.append(store.add_reference(ot_dir, ref))
        existing.add(label.lower())
    return created


# --- LLM extraction ---------------------------------------------------------------


def _llm_prompt(paper_id: str, title: str | None, labels: list[str], excerpt: str) -> str:
    known = ", ".join(labels[:60]) + (" ..." if len(labels) > 60 else "")
    return (
        "You are extracting the numbered results of a mathematics paper into structured "
        "records. Use ONLY the paper text below; do not add results that are not stated "
        "there and do not invent numbers.\n\n"
        f"Paper: {paper_id}" + (f" — {title}" if title else "") + "\n"
        f"Numbered results detected in the text: {known or '(none detected)'}\n\n"
        'Return a JSON list (no prose) of objects with keys: label (e.g. "Theorem 2.1"), '
        'title (name in parentheses if any, else ""), statement (the full statement), '
        "assumptions (list of hypothesis phrases), quantifiers (list of quantifier phrases "
        'such as "for every finite group G"), conclusion (the asserted conclusion), page '
        "(integer or null), section (title or null).\n\n"
        "Paper text:\n" + excerpt
    )


def _parse_llm_items(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        raw = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for item in raw[:100]:
        if isinstance(item, dict) and str(item.get("label", "")).strip():
            items.append(item)
    return items


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _acquire_provider(
    ot_dir: Path,
    pool: ProviderPool | None,
    provider: BaseProvider | None,
    config: Config | None,
) -> tuple[BaseProvider, ProviderLease | None]:
    """``(provider, lease)``: via the routing pool, else the explicitly given provider.

    An explicit ``pool`` is used as is; with neither pool nor provider one is built
    for the workspace so ``theorem_extraction`` is routed and recorded like every
    other task class. Only an explicitly passed ``provider`` bypasses the pool (a
    test double, or a caller that already leased). The pool import is lazy so the
    heuristic path never pays for the provider package.
    """
    from opentorus.providers.pool import TaskClass, build_pool

    if pool is None and provider is not None:
        return provider, None
    if pool is None:
        pool = build_pool(config if config is not None else _load_config(ot_dir), ot_dir)
    lease = pool.acquire(TaskClass.theorem_extraction)
    return lease.provider, lease


def _load_config(ot_dir: Path) -> Config:
    from opentorus.config import CONFIG_FILENAME, default_config, load_config

    path = ot_dir / CONFIG_FILENAME
    return load_config(path) if path.is_file() else default_config()


def extract_with_llm(
    ot_dir: Path,
    paper_id: str,
    *,
    problem_id: str | None = None,
    pool: ProviderPool | None = None,
    provider: BaseProvider | None = None,
    config: Config | None = None,
) -> list[TheoremReference]:
    """Ask a model to structure the paper's results; keep only locatable candidates.

    Every proposed label is validated with :func:`validate_locator`; labels the
    corpus demonstrably lacks are dropped (logged), and the excerpt/hash always
    come from the local source, never from the model's text. Results are
    ``candidate`` regardless of how confident the model sounds.
    """
    from opentorus.agent.session import SessionMessage
    from opentorus.research.papers import get_paper

    pid, corpus, text_path = _require_corpus(ot_dir, paper_id)
    paper = get_paper(ot_dir, pid)
    llm_provider, lease = _acquire_provider(ot_dir, pool, provider, config)

    labels = discover_labels(corpus)
    prompt = _llm_prompt(pid, paper.title if paper else None, labels, corpus[:_LLM_MAX_CHARS])
    response = llm_provider.respond([SessionMessage(role="user", content=prompt)])
    items = _parse_llm_items(getattr(response, "content", "") or "")

    model_name = getattr(llm_provider, "model_name", None)
    decision = getattr(lease, "decision", None) if lease is not None else None
    routing_decision_id = getattr(decision, "decision_id", None) if decision else None

    existing = {
        (r.theorem_label or "").lower() for r in store.list_references(ot_dir, paper_id=pid)
    }
    created: list[TheoremReference] = []
    for item in items:
        label = " ".join(str(item.get("label", "")).split())
        keyword, number = parse_label(label)
        if number is None:
            logger.warning("LLM proposed an unnumbered label %r for %s; skipped", label, pid)
            continue
        label = f"{keyword.capitalize()} {number}" if keyword else number
        if label.lower() in existing:
            continue
        section_raw = item.get("section")
        locator = SourceLocator(
            paper_id=pid,
            label=label,
            page=_as_int(item.get("page")),
            section=str(section_raw).strip() if section_raw else None,
            source_path=text_path,
        )
        validation = validate_locator(ot_dir, locator)
        if not validation.ok:
            # The label is what makes a reference real: a number the corpus lacks
            # is dropped outright. A wrong page/section is model-invented metadata
            # around a real statement, so it is removed rather than kept or trusted.
            label_only = SourceLocator(paper_id=pid, label=label, source_path=text_path)
            retry = validate_locator(ot_dir, label_only)
            if not retry.ok:
                logger.warning(
                    "LLM proposed %s for %s but the local source disagrees: %s",
                    label,
                    pid,
                    "; ".join(validation.errors),
                )
                continue
            logger.warning(
                "LLM proposed %s for %s with an unverifiable locator (%s); kept without it",
                label,
                pid,
                "; ".join(validation.errors),
            )
            locator, validation = label_only, retry
        context = validation.context or located_context(ot_dir, locator, width=_CONTEXT_WIDTH)
        ref = _build_reference(
            paper_id=pid,
            label=label,
            context=context or "",
            problem_id=problem_id,
            extraction_method="llm",
            source_path=text_path,
            page=locator.page,
            section=locator.section,
            llm_fields={
                "title": str(item.get("title") or "").strip(),
                "statement": str(item.get("statement") or "").strip(),
                "assumptions": _as_str_list(item.get("assumptions")),
                "quantifiers": _as_str_list(item.get("quantifiers")),
                "conclusion": str(item.get("conclusion") or "").strip(),
                "extracting_model": str(model_name) if model_name else None,
                "routing_decision_id": routing_decision_id,
            },
        )
        created.append(store.add_reference(ot_dir, ref))
        existing.add(label.lower())
    return created
