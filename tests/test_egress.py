"""Tests for the network-egress policy and runtime guard (Milestone 44).

No real network is used. We verify: egress is blocked in safe/review; ask mode
confirms each new host once; per-host rate limit and the daily budget are
enforced; and credentials never appear in a redacted log line.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from opentorus.permissions.policy import evaluate_egress, is_sensitive_path
from opentorus.research.egress import EgressBlocked, EgressGuard, host_of, redact


def test_host_of_strips_scheme_credentials_and_port() -> None:
    assert host_of("https://user:pw@api.crossref.org:443/works?q=x") == "api.crossref.org"
    assert host_of("export.arxiv.org/api/query") == "export.arxiv.org"


def test_policy_blocks_egress_in_safe_and_review() -> None:
    assert evaluate_egress("api.x.org", "safe").allowed is False
    assert evaluate_egress("api.x.org", "trusted", review=True).allowed is False


def test_policy_ask_requires_confirmation() -> None:
    decision = evaluate_egress("api.x.org", "ask")
    assert decision.allowed is True
    assert decision.requires_confirmation is True


def test_policy_trusted_fast_no_confirmation() -> None:
    decision = evaluate_egress("api.x.org", "trusted", style="fast")
    assert decision.allowed is True
    assert decision.requires_confirmation is False


def test_guard_blocks_in_safe_mode() -> None:
    guard = EgressGuard("safe")
    with pytest.raises(EgressBlocked):
        guard.authorize("https://api.openalex.org/works")


def test_guard_confirms_each_host_once() -> None:
    asked: list[str] = []

    def confirm(host: str) -> bool:
        asked.append(host)
        return True

    guard = EgressGuard("ask", confirm=confirm)
    guard.authorize("https://api.openalex.org/a")
    guard.authorize("https://api.openalex.org/b")  # same host: no second prompt
    guard.authorize("https://api.crossref.org/c")
    assert asked == ["api.openalex.org", "api.crossref.org"]


def test_guard_denied_when_not_confirmed() -> None:
    guard = EgressGuard("ask", confirm=lambda host: False)
    with pytest.raises(EgressBlocked):
        guard.authorize("https://api.openalex.org/works")


def test_guard_enforces_rate_limit() -> None:
    ticks = itertools.count(0.0, 0.1)  # all within the same 60s window
    guard = EgressGuard("trusted", style="fast", rate_limit_per_minute=3, clock=lambda: next(ticks))
    for _ in range(3):
        guard.authorize("https://api.openalex.org/works")
    with pytest.raises(EgressBlocked, match="Rate limit"):
        guard.authorize("https://api.openalex.org/works")


def test_guard_rate_limit_window_resets() -> None:
    times = iter([0.0, 0.0, 120.0])  # third call is well outside the 60s window
    guard = EgressGuard("trusted", style="fast", rate_limit_per_minute=1, clock=lambda: next(times))
    guard.authorize("https://api.openalex.org/works")
    with pytest.raises(EgressBlocked):
        guard.authorize("https://api.openalex.org/works")
    guard.authorize("https://api.openalex.org/works")  # window elapsed -> allowed


def test_guard_enforces_daily_budget_and_persists(tmp_path: Path) -> None:
    ledger = tmp_path / "egress.json"
    guard = EgressGuard("trusted", style="fast", daily_request_budget=2, ledger_path=ledger)
    guard.authorize("https://api.openalex.org/1")
    guard.authorize("https://api.crossref.org/2")
    with pytest.raises(EgressBlocked, match="budget"):
        guard.authorize("https://api.x.org/3")
    # A fresh guard reloads today's count from the ledger and stays blocked.
    reloaded = EgressGuard("trusted", style="fast", daily_request_budget=2, ledger_path=ledger)
    with pytest.raises(EgressBlocked, match="budget"):
        reloaded.authorize("https://api.x.org/4")


def test_redact_hides_credentials() -> None:
    url = "https://api.springernature.com/meta/v2/json?q=x&api_key=SECRET123&p=5"
    out = redact(url)
    assert "SECRET123" not in out
    assert "REDACTED" in out
    assert "q=x" in out


def test_institutional_session_files_are_sensitive() -> None:
    assert is_sensitive_path("cookies.txt")
    assert is_sensitive_path("/home/u/springer_api_key")
    assert is_sensitive_path(Path("session.cookies"))


def test_rate_limit_survives_the_per_call_guard_the_tools_build(tmp_path: Path) -> None:
    """The throttle has to live in the ledger, not in one guard's memory.

    Every literature tool constructs a **fresh** EgressGuard per invocation, so the
    in-memory window is always empty and never throttled anything in production.
    Measured at 2/min: one reused guard blocks the third request, a fresh guard per
    request allowed six in a row — the bulk harvesting the daily budget alone was
    never meant to be the only defence against.
    """
    ledger = tmp_path / "egress.json"

    def fresh() -> EgressGuard:
        return EgressGuard(
            "trusted",
            style="autonomous",
            rate_limit_per_minute=2,
            daily_request_budget=1000,
            ledger_path=ledger,
        )

    fresh().authorize("https://api.openalex.org/works")
    fresh().authorize("https://api.openalex.org/works")
    with pytest.raises(EgressBlocked, match="Rate limit"):
        fresh().authorize("https://api.openalex.org/works")

    # Per host, not globally: a different source is unaffected.
    fresh().authorize("https://arxiv.org/abs/1234.5678")


def test_rate_limit_ledger_tolerates_a_file_written_before_it_existed(tmp_path: Path) -> None:
    """An older ledger has only day/count; it must not break the guard."""
    ledger = tmp_path / "egress.json"
    ledger.write_text('{"day": "1999-01-01", "count": 7}', encoding="utf-8")
    guard = EgressGuard(
        "trusted",
        style="autonomous",
        rate_limit_per_minute=2,
        daily_request_budget=1000,
        ledger_path=ledger,
    )
    assert guard.authorize("https://api.openalex.org/works") == "api.openalex.org"
