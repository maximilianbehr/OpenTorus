"""Tests for review gating & resolution (Milestone 60)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.review import (
    gate_publication,
    open_blocking_findings,
    resolve_finding,
    review_target,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _blocking_claim(ot: Path):
    from opentorus.research.claims import new_claim

    claim = new_claim(ot, "We have proven the main theorem. QED.")
    review = review_target(ot, claim.id)
    return claim, review


def test_blocking_findings_block_publication_in_review_mode(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim, _ = _blocking_claim(ot)
    decision = gate_publication(ot, claim.id, review_mode=True)
    assert decision.allowed is False
    assert decision.blocking


def test_advisory_in_normal_mode(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim, _ = _blocking_claim(ot)
    decision = gate_publication(ot, claim.id, review_mode=False)
    assert decision.allowed is True
    assert decision.enforced is False
    assert decision.blocking


def test_resolving_clears_the_gate(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim, review = _blocking_claim(ot)
    blocking = open_blocking_findings(ot, claim.id)
    assert blocking
    for finding in blocking:
        resolve_finding(ot, review.id, finding.finding_id, "accepted", note="revised")
    decision = gate_publication(ot, claim.id, review_mode=True)
    assert decision.allowed is True
    assert not open_blocking_findings(ot, claim.id)


def test_disputing_also_clears_the_gate(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim, review = _blocking_claim(ot)
    fid = open_blocking_findings(ot, claim.id)[0].finding_id
    resolve_finding(ot, review.id, fid, "disputed", note="meta commentary")
    for finding in open_blocking_findings(ot, claim.id):
        resolve_finding(ot, review.id, finding.finding_id, "disputed", note="meta")
    assert gate_publication(ot, claim.id, review_mode=True).allowed is True


def test_research_loop_runs_critic_and_journals_it(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    from opentorus.agent.research_loop import run_research
    from opentorus.config import default_config
    from opentorus.providers.mock_provider import MockProvider
    from opentorus.research.journal import list_entries

    run_research(tmp_path, ot, MockProvider(), default_config(), "Is P bounded?", max_iterations=1)
    entries = list_entries(ot)
    assert entries
