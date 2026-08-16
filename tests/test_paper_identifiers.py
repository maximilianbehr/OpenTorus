"""Tests for DOI / arXiv identifier normalization."""

from __future__ import annotations

import pytest

from opentorus.research.identifiers import IdentifierError, normalize_paper_identifier
from opentorus.research.papers import Paper, format_paper_agent_line, paper_fetch_identifier


@pytest.mark.parametrize(
    ("raw", "kind", "normalized"),
    [
        ("2504.01500", "arxiv", "2504.01500"),
        ("1112.1588v2", "arxiv", "1112.1588v2"),
        ("https://arxiv.org/abs/2504.01500", "arxiv", "2504.01500"),
        ("https://arxiv.org/pdf/2504.01500.pdf", "arxiv", "2504.01500"),
        ("arxiv:2504.01500", "arxiv", "2504.01500"),
        ("10.1137/0612020", "doi", "10.1137/0612020"),
        ("https://doi.org/10.1137/0612020", "doi", "10.1137/0612020"),
        ("doi:10.1137/0612020", "doi", "10.1137/0612020"),
    ],
)
def test_normalize_paper_identifier(raw: str, kind: str, normalized: str) -> None:
    got_kind, got_id = normalize_paper_identifier(raw)
    assert got_kind == kind
    assert got_id == normalized


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "PAPER-0001",
        "not-an-id",
    ],
)
def test_normalize_rejects_garbage(bad: str) -> None:
    with pytest.raises(IdentifierError):
        normalize_paper_identifier(bad)


def test_paper_fetch_identifier_from_fields() -> None:
    assert (
        paper_fetch_identifier(Paper(id="PAPER-0001", source="x", source_type="doi", doi="10.1/x"))
        == "10.1/x"
    )
    assert (
        paper_fetch_identifier(
            Paper(id="PAPER-0001", source="x", source_type="arxiv", arxiv_id="2504.01500")
        )
        == "2504.01500"
    )


def test_paper_fetch_identifier_from_arxiv_url() -> None:
    paper = Paper(
        id="PAPER-0001",
        source="https://arxiv.org/abs/2504.01500",
        source_type="url",
    )
    assert paper_fetch_identifier(paper) == "2504.01500"


def test_format_paper_agent_line_includes_fetch() -> None:
    line = format_paper_agent_line(
        Paper(
            id="PAPER-0001",
            source="https://arxiv.org/abs/2504.01500",
            source_type="arxiv",
            title="Sign paper",
            arxiv_id="2504.01500",
            full_text_accessible=True,
        )
    )
    assert 'fetch="2504.01500"' in line
    assert 'read=paper_read("PAPER-0001")' in line


# --- artifact ids a model writes by hand ---------------------------------------


@pytest.mark.parametrize(
    ("written", "canonical"),
    [
        ("PAPER-002", "PAPER-0002"),
        ("paper-2", "PAPER-0002"),
        (" claim-0007 ", "CLAIM-0007"),
        ("PROBLEM-1", "PROBLEM-0001"),
        ("EXP-0001", "EXP-0001"),
        ("PAPER-12345", "PAPER-12345"),
    ],
)
def test_short_artifact_ids_resolve_to_the_minted_form(written: str, canonical: str) -> None:
    """Ids are minted as PREFIX-%04d, so a short form is unambiguous.

    A Coq calibration run wrote three-digit ids throughout; paper_read answered "No
    PAPER-002 ... call paper_fetch first", which is true and useless — the paper was
    sitting in the workspace as PAPER-0002.
    """
    from opentorus.jsonl import canonical_artifact_id

    assert canonical_artifact_id(written) == canonical


@pytest.mark.parametrize("raw", ["", "not-an-id", "PAPER", "2504.01500", "PAPER-0001v2"])
def test_non_ids_are_left_alone(raw: str) -> None:
    """Anything that is not PREFIX-<digits> must still miss, and still say so."""
    from opentorus.jsonl import canonical_artifact_id

    assert canonical_artifact_id(raw) == raw.strip().upper()
