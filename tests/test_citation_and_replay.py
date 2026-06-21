"""Tests for batch-10: cited-theorem source advisory, dossier replay diff, /doctor."""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.research.dossier import store
from opentorus.research.dossier.experiments import (
    _save_manifest,
    create_experiment,
    get_experiment,
    run_experiment,
)
from opentorus.research.paper_citations import theorem_context, validate_proof_citations
from opentorus.research.papers import Paper, _save_meta, papers_dir
from opentorus.workspace import init_workspace, workspace_dir


def test_theorem_context_extracts_snippet() -> None:
    corpus = "Intro text. Theorem 2.1. For all real x, f(x) is nonnegative. More text."
    ctx = theorem_context(corpus, "2.1")
    assert ctx is not None and "nonnegative" in ctx


def test_citation_advisory_surfaces_source_text(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    pid = "PAPER-0001"
    _save_meta(
        ot,
        Paper(
            id=pid,
            source="x",
            source_type="manual",
            structure_path=f"papers/{pid}/structure.json",
        ),
    )
    struct = papers_dir(ot) / pid / "structure.json"
    struct.parent.mkdir(parents=True, exist_ok=True)
    struct.write_text(
        json.dumps({"sections": [{"text": "Theorem 2.1. For all real x, f(x) is nonnegative."}]}),
        encoding="utf-8",
    )

    errors, warnings = validate_proof_citations(ot, "By Theorem 2.1 of PAPER-0001 the bound holds.")
    assert not errors  # the theorem exists in the parsed corpus
    assert any("source context" in w for w in warnings)


def test_dossier_replay_reports_reproducibility(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    pid = store.create_dossier(ot, "A problem.").id
    exp = create_experiment(ot, pid, title="det", command='python3 -c "print(42)"')

    first = run_experiment(ot, pid, exp.experiment_id)
    assert first.status == "succeeded"
    assert first.stdout_sha256  # baseline recorded

    second = run_experiment(ot, pid, exp.experiment_id)
    assert "reproducible" in second.result_summary.lower()

    # Simulate drift: tamper the recorded baseline, then a same-output run flags it.
    rec = get_experiment(ot, pid, exp.experiment_id)
    rec.stdout_sha256 = "deadbeef"
    _save_manifest(ot, rec)
    third = run_experiment(ot, pid, exp.experiment_id)
    assert "non-reproducible" in third.result_summary.lower()


def test_repl_doctor_command(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    from opentorus.repl import dispatch

    result = dispatch("/doctor")
    assert not result.should_exit
    assert any("Doctor:" in m for m in result.messages)
