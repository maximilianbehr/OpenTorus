"""Collecting is not progress.

The original search-spam guard counted *consecutive* searches, which measures the wrong
thing: a run that alternates search, search, fetch, search, search, fetch resets the
counter on every fetch and never trips it, while doing nothing with what it collects.
Observed in a real run (marcus-de-oliveira): 115 actions — 39 web_search, 33 lit_search,
31 paper_fetch, but only 5 paper_read and zero proof_write. paper_fetch is acquisition,
not processing: it puts a file on disk and tells the model nothing.

Thresholds are calibrated against twelve recorded runs, whose end-of-run ratios separate
cleanly (21.2x for the pathological one; 0.2x-1.6x for the other eleven).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.agent.loop import (
    _ACQUISITION_MIN,
    _ACQUISITION_RATIO,
    AgentLoop,
)
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


@pytest.fixture
def loop(tmp_path: Path) -> AgentLoop:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    return AgentLoop(tmp_path, ot, MockProvider(), registry, default_config())


def _feed(loop: AgentLoop, names: list[str]) -> list[str | None]:
    """Replay a tool sequence through the counters and collect the nudges."""
    from opentorus.agent.loop import _SEARCH_STREAK_NEUTRAL, _SEARCH_STREAK_TOOLS

    nudges: list[str | None] = []
    for name in names:
        if name in _SEARCH_STREAK_TOOLS:
            loop._search_streak += 1
        elif name not in _SEARCH_STREAK_NEUTRAL:
            loop._search_streak = 0
        if name in {"lit_search", "web_search", "paper_fetch", "fetch_url"}:
            loop._acquisition_calls += 1
        elif name not in _SEARCH_STREAK_NEUTRAL:
            loop._processing_calls += 1
        nudges.append(loop._acquisition_nudge(name))
    return nudges


def test_interleaved_fetches_no_longer_hide_the_imbalance(loop: AgentLoop) -> None:
    """The pattern the consecutive-streak guard structurally cannot see."""
    sequence = ["lit_search", "web_search", "paper_fetch"] * 9
    nudges = _feed(loop, sequence)

    # The streak never reaches its threshold: the fetch resets it every third call.
    assert loop._search_streak < 4
    fired = [n for n in nudges if n]
    assert fired, "an acquisition-only run must be told to stop collecting"
    assert "Collecting is not progress" in fired[0]
    assert "paper_read what you already have" in fired[0]


def test_a_balanced_run_is_never_nagged(loop: AgentLoop) -> None:
    """Healthy runs alternate acquisition and processing; they must stay silent."""
    sequence = ["lit_search", "paper_fetch", "paper_read", "memory_add"] * 10
    assert all(n is None for n in _feed(loop, sequence))


def test_early_literature_work_is_left_alone(loop: AgentLoop) -> None:
    """A literature phase is legitimately acquisition-heavy before anything is read."""
    nudges = _feed(loop, ["lit_search", "paper_fetch"] * (_ACQUISITION_MIN // 2 - 1))
    assert all(n is None for n in nudges)


def test_the_original_spam_case_still_fires_immediately(loop: AgentLoop) -> None:
    """Eleven searches with no fetch at all — the failure the streak was built for."""
    nudges = _feed(loop, ["lit_search"] * 11)
    fired = [n for n in nudges if n]
    assert fired
    assert "consecutive search" in fired[0]
    # It fires on the 4th search, long before the ratio minimum is reached.
    assert nudges[3] is not None
    assert 4 < _ACQUISITION_MIN


def test_processing_pulls_the_run_back_out_of_the_warning(loop: AgentLoop) -> None:
    """The nudge is a state, not a punishment: do the work and it stops."""
    _feed(loop, ["lit_search", "paper_fetch"] * 12)
    assert _feed(loop, ["paper_fetch"])[0] is not None

    reads = int(loop._acquisition_calls / _ACQUISITION_RATIO) + 1
    _feed(loop, ["paper_read"] * reads)
    assert _feed(loop, ["lit_search"])[0] is None


def test_nudge_only_rides_on_acquisition_calls(loop: AgentLoop) -> None:
    """A run that has turned to processing must not be nagged on its own results."""
    _feed(loop, ["lit_search", "paper_fetch"] * 12)
    assert loop._acquisition_nudge("paper_read") is None
    assert loop._acquisition_nudge("proof_write") is None
    assert loop._acquisition_nudge("status") is None


def test_inventory_polls_count_as_neither(loop: AgentLoop) -> None:
    """status/paper_list must not launder an acquisition run into a balanced one."""
    _feed(loop, ["lit_search", "paper_fetch"] * 8)
    before = (loop._acquisition_calls, loop._processing_calls)
    _feed(loop, ["status", "paper_list", "memory_list"])
    assert (loop._acquisition_calls, loop._processing_calls) == before
