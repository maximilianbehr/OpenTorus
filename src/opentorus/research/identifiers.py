"""Normalize DOI / arXiv identifiers for paper_fetch and CLI."""

from __future__ import annotations

import re
from typing import Literal

from opentorus.errors import OpenTorusError

IdentifierKind = Literal["doi", "arxiv"]

_ARXIV_URL = re.compile(
    r"(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)"
    r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?)",
    re.I,
)
_ARXIV_BARE = re.compile(
    r"^(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?)$",
    re.I,
)
_DOI_URL = re.compile(r"(?:https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/\S+)", re.I)
_DOI_BARE = re.compile(r"^(10\.\d{4,9}/\S+)$", re.I)

_FORMAT_HINT = (
    "Use a bare arXiv id (e.g. 2504.01500 or 1112.1588v2), a DOI (10.1137/0612020), "
    "or a full https://arxiv.org/abs/… / https://doi.org/… URL — not a mangled number."
)


class IdentifierError(OpenTorusError):
    """Raised when a paper identifier cannot be parsed."""


def _trim_doi(doi: str) -> str:
    return doi.rstrip(".,;)>]")


def normalize_paper_identifier(raw: str) -> tuple[IdentifierKind, str]:
    """Return ``(kind, normalized_id)`` from user or model input."""
    text = raw.strip()
    if not text:
        raise IdentifierError(f"Empty identifier. {_FORMAT_HINT}")

    m = _DOI_URL.search(text)
    if m:
        return "doi", _trim_doi(m.group(1))
    if text.lower().startswith("doi:"):
        text = text[4:].strip()
    if _DOI_BARE.match(text):
        return "doi", _trim_doi(text)

    m = _ARXIV_URL.search(text)
    if m:
        return "arxiv", m.group(1)
    if _ARXIV_BARE.match(text):
        return "arxiv", _ARXIV_BARE.match(text).group(1)  # type: ignore[union-attr]

    raise IdentifierError(f"Unrecognized paper identifier {raw!r}. {_FORMAT_HINT}")
