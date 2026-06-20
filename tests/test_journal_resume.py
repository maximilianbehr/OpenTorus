"""Tests for the research journal and resumption (Milestone 54).

A paused investigation resumes at the right step; the journal reflects all
iterations; and a bundle round-trips the state. No network is used.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.research_loop import load_state, run_research
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.research.journal import list_entries, search_entries
from opentorus.workspace import init_workspace, workspace_dir


def _setup(tmp_path: Path):
    init_workspace(tmp_path)
    return tmp_path, workspace_dir(tmp_path)


def test_paused_investigation_resumes_at_next_step(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    question = "Resumable investigation?"
    first = run_research(root, ot, MockProvider(), default_config(), question, max_iterations=1)
    assert first.total_iterations == 1
    claim_id = first.results[0].claim_id

    # Resume with a higher cap: it continues from iteration 2, not from scratch.
    second = run_research(root, ot, MockProvider(), default_config(), question, max_iterations=3)
    assert second.iterations_run == 2  # iterations 2 and 3
    assert second.total_iterations == 3
    assert second.results[0].iteration == 2
    # Same investigation: same target claim is reused, not recreated.
    assert second.results[0].claim_id == claim_id

    state = load_state(ot, question)
    assert state is not None and state.completed_iterations == 3


def test_journal_reflects_all_iterations(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    run_research(root, ot, MockProvider(), default_config(), "Journalled run.", max_iterations=3)
    entries = list_entries(ot)
    assert [e.iteration for e in entries] == [1, 2, 3]
    assert all(e.actions for e in entries)
    # Searchable.
    assert search_entries(ot, "corpus")


def test_bundle_round_trips_research_state(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    run_research(root, ot, MockProvider(), default_config(), "Bundled run.", max_iterations=2)

    # A session message is required for export; seed one tied to a session id.
    from opentorus.agent.session import SessionMessage, append_message

    append_message(ot, SessionMessage(role="user", content="ctx", metadata={"session_id": "S1"}))

    from opentorus.bundle import export_session, import_bundle

    bundle = export_session(ot, "S1")
    dest = import_bundle(ot, bundle, dest=tmp_path / "review")

    # Journal and research state survive the round-trip.
    assert (dest / "artifacts" / "journal" / "journal.jsonl").is_file()
    research_files = list((dest / "artifacts" / "research").glob("*.json"))
    assert research_files, "research state should be bundled"
