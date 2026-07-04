"""The agent's workspace-level experiments must be visible to dossier consumers.

Regression (found in a live prove run): exp_new/exp_run record workspace-level
``.opentorus/experiments/EXP-*``, but the report, the status gate, the PDF export,
and the experiment-citation check read only ``problems/<pid>/experiments/`` — so a
dossier with 7 completed docker runs rendered "## Experiments … (none)", could never
derive EXPERIMENTAL_ONLY, and citing the runs as evidence was rejected as fabrication.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import store
from opentorus.research.dossier.claims import add_claim, add_evidence, proof_evidence_count
from opentorus.research.dossier.experiments import (
    get_problem_experiment,
    list_problem_experiments,
)
from opentorus.research.dossier.report import build_report
from opentorus.research.dossier.status_gate import derive_status
from opentorus.research.experiments import _save_meta, new_experiment
from opentorus.workspace import init_workspace, workspace_dir


def _ws_completed_experiment(ot, *, problem_id: str | None):
    exp = new_experiment(
        ot, "delta sweep", command="python scripts/sweep.py", problem_id=problem_id
    )
    exp.status = "completed"
    _save_meta(ot, exp)
    return exp


def test_merged_view_includes_workspace_experiments(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Prove X.", title="Problem X")
    exp = _ws_completed_experiment(ot, problem_id="PROBLEM-0001")

    merged = list_problem_experiments(ot, "PROBLEM-0001")
    assert [e.experiment_id for e in merged] == [exp.id]
    assert merged[0].status == "succeeded"  # completed → ran, for the status gate
    assert proof_evidence_count(ot, "PROBLEM-0001") == 1

    looked_up = get_problem_experiment(ot, "PROBLEM-0001", exp.id)
    assert looked_up is not None and looked_up.experiment_id == exp.id


def test_report_lists_workspace_experiments(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Prove X.", title="Problem X")
    exp = _ws_completed_experiment(ot, problem_id="PROBLEM-0001")

    report = build_report(ot, "PROBLEM-0001", harvest_session=False)
    assert exp.id in report
    assert "- (none)" not in report.split("## Experiments")[1].split("##")[0]


def test_status_gate_sees_workspace_experiments(tmp_path: Path) -> None:
    """EXPERIMENTAL_ONLY must be derivable from agent-run (workspace) experiments."""
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Prove X.", title="Problem X")
    _ws_completed_experiment(ot, problem_id="PROBLEM-0001")

    verdict = derive_status(ot, "PROBLEM-0001")
    assert verdict.status == "EXPERIMENTAL_ONLY"


def test_evidence_can_cite_workspace_experiment(tmp_path: Path) -> None:
    """Citing an agent-run EXP-* is citing a real manifest, not a fabrication."""
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Prove X.", title="Problem X")
    exp = _ws_completed_experiment(ot, problem_id="PROBLEM-0001")
    claim = add_claim(
        ot,
        "PROBLEM-0001",
        claim_type="EXPERIMENTAL_OBSERVATION",
        statement="Observed monotone decay in the sweep.",
    )
    evidence, advisory = add_evidence(
        ot,
        "PROBLEM-0001",
        claim.id,
        evidence_type="EXPERIMENT",
        summary="Sweep supports the observation.",
        source_artifacts=[exp.id],
    )
    assert evidence.id.startswith("EVID-")
    assert advisory is None  # completed run → no 'planned, not run' advisory

    # A created-but-never-run workspace experiment still gets the honesty advisory.
    planned = new_experiment(ot, "unrun probe", command="python x.py", problem_id="PROBLEM-0001")
    _, advisory2 = add_evidence(
        ot,
        "PROBLEM-0001",
        claim.id,
        evidence_type="EXPERIMENT",
        summary="Cites an unrun probe.",
        source_artifacts=[planned.id],
    )
    assert advisory2 is not None and "not run" in advisory2
