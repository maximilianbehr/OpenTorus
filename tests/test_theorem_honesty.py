"""THMREF and the honesty surface: only a human-accepted reference licenses
knowledge-claim language; extraction (heuristic or LLM) never does by itself."""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.dossier import store as dossier_store
from opentorus.research.dossier.report import honesty_context
from opentorus.research.papers import acquire_paper, read_paper
from opentorus.research.sources.base import SourceRecord
from opentorus.research.theorems import store
from opentorus.research.theorems.extraction import extract_heuristic, extract_with_llm
from opentorus.workspace import init_workspace

PAGES = [
    "1 Introduction\nWe study finite groups. By Theorem 2.1 we get the bound.\n",
    (
        "2 Main results\n"
        "Theorem 2.1 (Main theorem). Let G be a finite group of order n. "
        "Then every element of G has order dividing n.\n"
        "Proof. Omitted.\n"
        "Lemma 2.2. Suppose H is a subgroup of G. Then |H| divides |G|.\n"
    ),
]


class _JsonProvider(BaseProvider):
    """A scripted provider returning a fixed JSON list (no network, no mock keywords)."""

    name = "fake"
    model_name = "fake-extractor-1"

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def generate(self, messages, tools=None):
        self.prompts.append(messages[-1].content)
        return ProviderResponse(kind="message", content="Sure:\n" + json.dumps(self.payload))


def _setup(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    ot = tmp_path / ".opentorus"
    record = SourceRecord(source="arxiv", title="Finite groups", arxiv_id="2401.00001")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    read_paper(ot, paper.id, page_extractor=lambda p: list(PAGES))
    dossier_store.create_dossier(ot, "Every element of a finite group has order dividing |G|.")
    return ot, paper.id


def test_candidate_thmref_does_not_license_knowledge_claims(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    assert honesty_context(ot, "PROBLEM-0001") == (False, False, False)
    refs = extract_heuristic(ot, pid, problem_id="PROBLEM-0001")
    assert refs and all(r.review_status == "candidate" for r in refs)
    assert honesty_context(ot, "PROBLEM-0001")[1] is False


def test_rejected_thmref_does_not_license(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    refs = extract_heuristic(ot, pid, problem_id="PROBLEM-0001")
    for ref in refs:
        store.set_review_status(ot, ref.id, "rejected", "not the statement claimed")
    assert honesty_context(ot, "PROBLEM-0001")[1] is False


def test_accepted_thmref_licenses(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    refs = extract_heuristic(ot, pid, problem_id="PROBLEM-0001")
    store.set_review_status(ot, refs[0].id, "accepted", "verified against the source")
    has_proof, has_ref, has_thm = honesty_context(ot, "PROBLEM-0001")
    assert has_ref is True
    # The other two licenses are untouched: a reference is not a proof.
    assert (has_proof, has_thm) == (False, False)


def test_accepted_thmref_for_another_problem_does_not_license(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    dossier_store.create_dossier(ot, "A second, unrelated problem.")
    refs = extract_heuristic(ot, pid, problem_id="PROBLEM-0002")
    store.set_review_status(ot, refs[0].id, "accepted")
    assert honesty_context(ot, "PROBLEM-0001")[1] is False
    assert honesty_context(ot, "PROBLEM-0002")[1] is True


def test_llm_extraction_cannot_reach_accepted_without_review_command(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    provider = _JsonProvider(
        [
            {
                "label": "Theorem 2.1",
                "title": "Main theorem",
                "statement": "Every element of a finite group of order n has order dividing n.",
                "assumptions": ["G is a finite group of order n"],
                "quantifiers": ["for every element of G"],
                "conclusion": "the order of every element divides n",
                "page": 2,
                "section": "Main results",
                "review_status": "accepted",
            },
            # A number the local corpus does not contain: dropped, never recorded.
            {"label": "Theorem 7.7", "statement": "An invented result.", "page": 1},
            # A real result with a page beyond the parsed page count: kept, but the
            # invented page is removed rather than stored.
            {"label": "Lemma 2.2", "statement": "Lagrange.", "page": 40},
        ]
    )
    refs = extract_with_llm(ot, pid, problem_id="PROBLEM-0001", provider=provider)
    assert provider.prompts and "Theorem 2.1" in provider.prompts[0]
    assert [r.theorem_label for r in refs] == ["Theorem 2.1", "Lemma 2.2"]
    assert refs[1].locator.page is None
    assert refs[1].excerpt.startswith("Lemma 2.2. Suppose H is a subgroup")
    assert refs[1].review_status == "candidate"
    ref = refs[0]
    assert ref.review_status == "candidate"  # the model's "accepted" is ignored
    assert ref.extraction_method == "llm"
    assert ref.extracting_model == "fake-extractor-1"
    assert ref.routing_decision_id is None  # no pool lease was involved
    assert ref.assumptions == ["G is a finite group of order n"]
    assert ref.locator.page == 2 and ref.locator.section == "Main results"
    # Excerpt and hash come from the local source, not from the model text.
    assert ref.excerpt.startswith("Theorem 2.1 (Main theorem). Let G be a finite group")
    assert len(ref.location_hash) == 64
    assert store.list_references(ot, review_status="accepted") == []
    assert honesty_context(ot, "PROBLEM-0001")[1] is False
    # Only the human review path promotes.
    store.set_review_status(ot, ref.id, "accepted", "read the statement in the PDF")
    assert honesty_context(ot, "PROBLEM-0001")[1] is True


def test_llm_extraction_with_garbage_output_creates_nothing(tmp_path: Path) -> None:
    ot, pid = _setup(tmp_path)
    provider = _JsonProvider("not a list at all")
    assert extract_with_llm(ot, pid, provider=provider) == []
    assert store.list_references(ot) == []
