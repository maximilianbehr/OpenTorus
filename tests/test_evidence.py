"""Tests for the evidence ledger (Milestone 17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.claims import get_claim, new_claim
from opentorus.research.evidence import add_evidence, get_evidence, list_evidence
from opentorus.research.experiments import new_experiment, run_experiment
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_add_and_list_evidence_for_claim(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    claim = new_claim(ot, "Caching helps")
    # A cited experiment must exist and have run to completion; create + run it first.
    exp = new_experiment(ot, "latency sweep")
    run_experiment(ot, exp.id)
    ev, advisory = add_evidence(
        ot,
        claim.id,
        source_type="experiment",
        source_id=exp.id,
        summary="latency dropped",
        direction="supports",
        strength="moderate",
    )
    assert ev.id == "EVIDENCE-0001"
    assert advisory is None
    listed = list_evidence(ot, claim.id)
    assert len(listed) == 1
    assert get_evidence(ot, ev.id) is not None


def test_cite_nonexistent_experiment_rejected(tmp_path: Path) -> None:
    # Citing an EXP-* that was never created (a hallucinated id) is rejected:
    # evidence must point at a real artifact, never an invented one.
    ot = _ws(tmp_path)
    claim = new_claim(ot, "Caching helps")
    with pytest.raises(OpenTorusError):
        add_evidence(ot, claim.id, source_type="experiment", source_id="EXP-9999")


def test_cite_unrun_experiment_advises(tmp_path: Path) -> None:
    # A real but not-yet-run experiment may be cited, but the advisory flags that
    # its results do not exist yet.
    ot = _ws(tmp_path)
    claim = new_claim(ot, "Caching helps")
    exp = new_experiment(ot, "planned sweep")
    _, advisory = add_evidence(ot, claim.id, source_type="experiment", source_id=exp.id)
    assert advisory is not None and "not run" in advisory.lower()


def test_contradictory_evidence_preserved_and_advised(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    claim = new_claim(ot, "Caching helps")
    add_evidence(ot, claim.id, source_type="experiment", direction="supports")
    ev2, advisory = add_evidence(
        ot, claim.id, source_type="log", direction="contradicts", summary="regression seen"
    )
    # Both records are preserved; nothing overwrites the supporting one.
    listed = list_evidence(ot, claim.id)
    assert len(listed) == 2
    assert advisory is not None and "review" in advisory.lower()
    # Adding contradictory evidence must NOT change the claim status.
    assert get_claim(ot, claim.id).status == "idea"


def test_invalid_fields_rejected(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    claim = new_claim(ot, "x")
    with pytest.raises(OpenTorusError):
        add_evidence(ot, claim.id, source_type="bogus")
    with pytest.raises(OpenTorusError):
        add_evidence(ot, claim.id, source_type="paper", direction="proves")
    with pytest.raises(OpenTorusError):
        add_evidence(ot, claim.id, source_type="paper", strength="overwhelming")


def test_list_filters_by_claim(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    add_evidence(ot, "CLAIM-0001", source_type="paper")
    add_evidence(ot, "CLAIM-0002", source_type="paper")
    assert len(list_evidence(ot, "CLAIM-0001")) == 1
    assert len(list_evidence(ot)) == 2
