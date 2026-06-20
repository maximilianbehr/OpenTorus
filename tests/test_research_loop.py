"""Tests for the autonomous research orchestrator (Milestone 53).

A seeded question advances through several iterations against the mock provider,
updates evidence/claims, respects the budget cap, and stops cleanly. No network.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.research_loop import load_state, run_research
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.research.evidence import list_evidence
from opentorus.research.journal import list_entries
from opentorus.workspace import init_workspace, workspace_dir


def _setup(tmp_path: Path):
    init_workspace(tmp_path)
    return tmp_path, workspace_dir(tmp_path)


def test_research_runs_iterations_and_records_evidence(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    outcome = run_research(
        root, ot, MockProvider(), default_config(), "Is P(n) bounded?", max_iterations=3
    )
    assert outcome.iterations_run == 3
    assert outcome.total_iterations == 3
    assert outcome.stopped_reason == "iteration cap reached"
    assert outcome.progress_path is not None
    # Each iteration produced bounded numerical evidence for the target claim.
    assert outcome.results[0].claim_id is not None
    assert list_evidence(ot, outcome.results[0].claim_id)
    assert len(list_entries(ot)) == 3


def test_research_advances_claim_to_numerical_evidence(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    outcome = run_research(
        root, ot, MockProvider(), default_config(), "Conjecture about n.", max_iterations=1
    )
    from opentorus.research.claims import get_claim

    claim = get_claim(ot, outcome.results[0].claim_id)
    assert claim is not None
    # Never auto-promoted past bounded numerical evidence.
    assert claim.status == "numerical_evidence"


def test_research_respects_token_budget(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    # A tiny token budget: the first iteration records usage, the next is refused.
    outcome = run_research(
        root,
        ot,
        MockProvider(),
        default_config(),
        "Budget-limited question.",
        max_iterations=10,
        token_budget=1,
    )
    assert outcome.iterations_run == 1
    assert outcome.stopped_reason == "token budget reached"


def test_research_persists_state(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    run_research(root, ot, MockProvider(), default_config(), "Persisted Q.", max_iterations=2)
    state = load_state(ot, "Persisted Q.")
    assert state is not None
    assert state.completed_iterations == 2
    assert state.target_claim_id is not None
    assert state.status == "completed"


def test_research_makes_checkpoints(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    run_research(root, ot, MockProvider(), default_config(), "Checkpoint Q.", max_iterations=2)
    from opentorus.research.checkpoints import list_checkpoints

    labels = [c.label for c in list_checkpoints(ot)]
    assert any("research" in label for label in labels)
