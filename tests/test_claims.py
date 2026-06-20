"""Tests for claim tracking and status discipline (Milestone 6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.claims import (
    ALLOWED_USAGE,
    get_claim,
    list_claims,
    new_claim,
    update_claim,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_new_claim_defaults_to_idea(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    claim = new_claim(base, "JSONL is inspectable.")
    assert claim.id == "CLAIM-0001"
    assert claim.status == "idea"
    assert claim.allowed_usage == ALLOWED_USAGE["idea"]


def test_ids_are_sequential(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_claim(base, "a")
    c2 = new_claim(base, "b")
    assert c2.id == "CLAIM-0002"
    assert len(list_claims(base)) == 2


def test_unrestricted_upgrade_allowed(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_claim(base, "a")
    updated = update_claim(base, "CLAIM-0001", status="hypothesis")
    assert updated.status == "hypothesis"
    assert updated.allowed_usage == ALLOWED_USAGE["hypothesis"]


def test_invalid_status_rejected(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_claim(base, "a")
    with pytest.raises(OpenTorusError):
        update_claim(base, "CLAIM-0001", status="totally_true")  # type: ignore[arg-type]


def test_restricted_upgrade_requires_confirmation(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_claim(base, "a")
    # No confirm callback -> refused.
    with pytest.raises(OpenTorusError):
        update_claim(base, "CLAIM-0001", status="verified")
    # Declined confirm -> refused.
    with pytest.raises(OpenTorusError):
        update_claim(base, "CLAIM-0001", status="verified", confirm=lambda c, n: False)
    # Approved confirm -> succeeds.
    updated = update_claim(base, "CLAIM-0001", status="verified", confirm=lambda c, n: True)
    assert updated.status == "verified"


def test_add_support(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_claim(base, "a")
    updated = update_claim(base, "CLAIM-0001", add_support="EXP-0001")
    assert "EXP-0001" in updated.support
    # idempotent
    updated2 = update_claim(base, "CLAIM-0001", add_support="EXP-0001")
    assert updated2.support.count("EXP-0001") == 1


def test_update_unknown_claim_raises(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        update_claim(base, "CLAIM-9999", status="evidence")


def test_get_claim(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    new_claim(base, "findable")
    assert get_claim(base, "CLAIM-0001").statement == "findable"
    assert get_claim(base, "CLAIM-0002") is None
