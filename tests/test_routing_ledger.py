"""The routing ledger: every acquire leaves a resolvable ``RTD-`` record, and the
loops that acquire through the pool stamp that id into the usage ledger."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.research_loop import run_research
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.providers.pool import (
    ProviderPool,
    TaskClass,
    read_routing_ledger,
    routing_ledger_path,
)
from opentorus.usage import read_usage
from opentorus.workspace import init_workspace, workspace_dir


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    init_workspace(tmp_path)
    return tmp_path, workspace_dir(tmp_path)


def test_pool_acquire_writes_rtd_record_for_proof_development(tmp_path: Path) -> None:
    _root, ot = _setup(tmp_path)
    lease = ProviderPool(default_config(), ot_dir=ot).acquire(TaskClass.proof_development)
    assert routing_ledger_path(ot) == ot / "usage" / "routing.jsonl"
    records = read_routing_ledger(ot)
    assert [r.decision_id for r in records] == ["RTD-0001"]
    assert records[0].task_class == "proof_development"
    assert records[0].selected_profile == "default"
    assert records[0].provider == "mock"
    assert records[0].configured_model == "mock-default"
    assert lease.decision == records[0]


def test_research_turn_stamps_routing_provenance_when_routing_enabled(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)
    config = default_config()
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"narration": ["default"]}
    run_research(root, ot, MockProvider(), config, "Routed narration?", max_iterations=1)

    usage = [r for r in read_usage(ot) if r.task_class == "narration"]
    assert usage, "the narration turn must be in the usage ledger"
    turn = usage[-1]
    assert turn.provider == "mock"
    assert turn.model == "mock-default"
    assert turn.selected_profile == "default"
    assert turn.requested_profile == "default"
    assert turn.configured_model == "mock-default"
    assert turn.actual_model == "mock-default"
    assert turn.routing_decision_id is not None and turn.routing_decision_id.startswith("RTD-")

    ledger = {r.decision_id: r for r in read_routing_ledger(ot)}
    decision = ledger[turn.routing_decision_id]
    assert decision.task_class == "narration"
    assert decision.selected_profile == "default"
    assert decision.routing_enabled is True
    assert decision.outcome == "selected"


def test_research_turn_with_routing_disabled_uses_the_given_provider(tmp_path: Path) -> None:
    root, ot = _setup(tmp_path)

    class Counting(MockProvider):
        def __init__(self) -> None:
            super().__init__()
            self.turns = 0

        def respond(
            self,
            messages,
            tools=None,
            on_text=None,
            *,
            stream=False,
            tool_choice=None,
            on_thinking=None,
        ):  # type: ignore[override]
            self.turns += 1
            return super().respond(messages, tools, on_text)

    provider = Counting()
    run_research(root, ot, provider, default_config(), "Plain narration?", max_iterations=1)
    assert provider.turns >= 1  # the injected provider answered
    assert not routing_ledger_path(ot).exists()  # nothing acquired, nothing recorded
    turn = [r for r in read_usage(ot) if r.task_class == "narration"][-1]
    assert turn.routing_decision_id is None
    assert turn.selected_profile is None
    assert turn.model == "mock-default"
    assert turn.actual_model == "mock-default"


def test_prove_cli_routes_proof_development_and_stamps_usage(tmp_path: Path, monkeypatch) -> None:
    """``opentorus prove`` leases its provider through the pool: the ledger holds an
    ``RTD-`` record for ``proof_development`` and every model turn of the run carries
    that decision id, so the usage ledger names the provider that actually answered."""
    from typer.testing import CliRunner

    from opentorus.cli import app
    from opentorus.research.dossier import store

    root, ot = _setup(tmp_path)
    store.create_dossier(ot, "For every n >= 1, the routed statement P(n) holds.")
    monkeypatch.chdir(root)
    result = CliRunner().invoke(app, ["prove", "PROBLEM-0001", "--no-literature"])
    assert result.exit_code == 0, result.stdout

    decisions = [r for r in read_routing_ledger(ot) if r.task_class == "proof_development"]
    assert decisions and decisions[0].outcome == "selected"
    assert decisions[0].selected_profile == "default"
    assert decisions[0].provider == "mock"

    turns = [r for r in read_usage(ot) if r.routing_decision_id is not None]
    assert turns, "prove's model turns must carry the routing decision id"
    assert {r.routing_decision_id for r in turns} == {decisions[0].decision_id}
    assert all(r.provider == "mock" and r.actual_model == "mock-default" for r in turns)
