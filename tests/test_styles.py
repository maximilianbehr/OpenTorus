"""Tests for operating styles (Milestone 22)."""

from __future__ import annotations

from pathlib import Path

from opentorus.permissions.policy import (
    evaluate_command,
    evaluate_write,
    is_destructive_command,
)
from opentorus.repl import dispatch
from opentorus.workspace import init_workspace


def test_default_normal_style_preserves_behavior() -> None:
    assert evaluate_command("ls", "safe").allowed is True  # harmless
    assert evaluate_command("pytest", "safe").allowed is False
    assert evaluate_command("pytest", "trusted").requires_confirmation is False
    assert evaluate_command("pytest", "ask").requires_confirmation is True
    assert evaluate_command("rm -rf /", "trusted").risk_level == "blocked"


def test_cautious_confirms_in_trusted() -> None:
    decision = evaluate_command("pytest", "trusted", style="cautious")
    assert decision.allowed is True
    assert decision.requires_confirmation is True
    write = evaluate_write("a.py", "trusted", style="cautious")
    assert write.requires_confirmation is True


def test_autonomous_low_risk_no_confirm_but_destructive_confirms() -> None:
    low = evaluate_command("pytest", "trusted", style="autonomous")
    assert low.allowed is True and low.requires_confirmation is False
    destructive = evaluate_command("rm notes.txt", "trusted", style="autonomous")
    assert destructive.allowed is True
    assert destructive.requires_confirmation is True
    # Autonomous never bypasses dangerous-command blocking.
    assert evaluate_command("rm -rf /", "trusted", style="autonomous").allowed is False


def test_autonomous_only_takes_effect_in_trusted() -> None:
    # In ask mode, autonomous still asks before non-harmless commands.
    decision = evaluate_command("pytest", "ask", style="autonomous")
    assert decision.requires_confirmation is True


def test_fast_confirms_destructive_only() -> None:
    assert evaluate_command("pytest", "trusted", style="fast").requires_confirmation is False
    assert evaluate_command("rm x", "trusted", style="fast").requires_confirmation is True


def test_is_destructive_command() -> None:
    assert is_destructive_command("rm file.txt") is True
    assert is_destructive_command("git reset --hard HEAD~1") is True
    assert is_destructive_command("git push --force") is True
    assert is_destructive_command("ls -la") is False


def test_repl_style_set_and_show(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    result = dispatch("/style cautious", start=tmp_path)
    assert "cautious" in result.messages[0]
    shown = dispatch("/style", start=tmp_path)
    assert "cautious" in shown.messages[0]
    bad = dispatch("/style bogus", start=tmp_path)
    assert "Unknown style" in bad.messages[0]
