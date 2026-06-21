"""Tests for the extended claim ledger (new types + needs_review status).

These pin the *honest defaults* required when adding claim types/statuses: a new
type never starts verified, and ``needs_review`` is reachable without a
verification artifact (it is a review flag, not a settled result).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.dossier import claims, store
from opentorus.research.dossier.models import CLAIM_STATUSES, CLAIM_TYPES
from opentorus.research.dossier.validation import default_status_for_type
from opentorus.workspace import init_workspace, workspace_dir


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    dossier = store.create_dossier(base, "A conjecture about objects X.", domain="test")
    return base, dossier.id


def test_new_types_registered() -> None:
    for t in ("HEURISTIC", "EXPERIMENTAL_OBSERVATION", "OPEN_GAP"):
        assert t in CLAIM_TYPES
    assert "needs_review" in CLAIM_STATUSES


@pytest.mark.parametrize("claim_type", ["HEURISTIC", "EXPERIMENTAL_OBSERVATION", "OPEN_GAP"])
def test_new_types_default_unverified(tmp_path: Path, claim_type: str) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type=claim_type, statement="some statement")
    assert c.status == "unverified"
    assert default_status_for_type(claim_type) == "unverified"  # type: ignore[arg-type]


def test_needs_review_does_not_require_verification(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    updated = claims.set_claim_status(base, pid, c.id, "needs_review")
    assert updated.status == "needs_review"


def test_verified_status_still_requires_artifact(tmp_path: Path) -> None:
    # Adding a status value must not weaken EVAL-001/EVAL-002: verified still needs an artifact.
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="HEURISTIC", statement="empirical regularity")
    with pytest.raises(OpenTorusError):
        claims.set_claim_status(base, pid, c.id, "verified")
    with pytest.raises(OpenTorusError):
        claims.set_claim_status(base, pid, c.id, "formally_verified")
