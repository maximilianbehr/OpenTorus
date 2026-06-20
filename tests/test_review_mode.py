"""Tests for review mode (Milestone 22)."""

from __future__ import annotations

from pathlib import Path

from opentorus.permissions.policy import (
    evaluate_claim_verification,
    evaluate_command,
    evaluate_read,
    evaluate_write,
)
from opentorus.repl import dispatch
from opentorus.workspace import init_workspace


def test_review_blocks_modifying_commands_but_allows_inspection() -> None:
    assert evaluate_command("ls", "trusted", review=True).allowed is True
    assert evaluate_command("git status", "trusted", review=True).allowed is True
    blocked = evaluate_command("pytest", "trusted", review=True)
    assert blocked.allowed is False
    assert blocked.risk_level == "blocked"


def test_review_still_blocks_dangerous() -> None:
    assert evaluate_command("rm -rf /", "trusted", review=True).risk_level == "blocked"


def test_review_blocks_writes() -> None:
    decision = evaluate_write("a.py", "trusted", review=True)
    assert decision.allowed is False
    assert decision.risk_level == "blocked"


def test_review_allows_reads_but_sensitive_still_confirmed() -> None:
    assert evaluate_read("README.md", "trusted").allowed is True
    assert evaluate_read(".env", "trusted").requires_confirmation is True


def test_review_blocks_claim_verification() -> None:
    blocked = evaluate_claim_verification(review=True)
    assert blocked.allowed is False
    allowed = evaluate_claim_verification(review=False)
    assert allowed.allowed is True
    assert allowed.requires_confirmation is True


def test_repl_mode_set_and_show(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    result = dispatch("/mode review", start=tmp_path)
    assert "review" in result.messages[0]
    shown = dispatch("/mode", start=tmp_path)
    assert "review" in shown.messages[0]
    bad = dispatch("/mode bogus", start=tmp_path)
    assert "Unknown mode" in bad.messages[0]
