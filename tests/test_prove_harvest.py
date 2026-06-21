"""Tests for prove-session harvest into dossier artifacts."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.prove_harvest import harvest_prove_session
from opentorus.agent.session import SessionMessage, append_message
from opentorus.research.dossier import store
from opentorus.workspace import init_workspace, workspace_dir


def test_harvest_counterexample_from_session(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Submodularity question.", title="Nyström error")

    append_message(
        ot,
        SessionMessage(
            role="assistant",
            content="",
            metadata={
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "run_shell",
                        "args": {"command": "python experiments/find_counterexample_sddm.py"},
                    }
                ],
                "session_id": "sess1",
            },
        ),
    )
    append_message(
        ot,
        SessionMessage(
            role="tool",
            content=(
                "exit_code=0\nstdout:\nCounterexample found!\nMatrix L:\n "
                "[[ 1.  0.  0.]\n [ 0.  2. -1.]\n [ 0. -1.  2.]]\n"
                "Violation details: {'A': (), 'B': (1,), 'i': 2}"
            ),
            metadata={"name": "run_shell", "session_id": "sess1"},
        ),
    )

    outcome = harvest_prove_session(ot, "PROBLEM-0001", session_id="sess1")
    assert outcome.harvested
    assert outcome.experiment_ids == ["EXP-0001"]
    assert outcome.claim_ids == ["CLAIM-0001"]
    assert outcome.proof_ids == ["PROOF-0001"]

    claims = store.list_claims(ot, "PROBLEM-0001")
    assert claims[0].type == "COUNTEREXAMPLE_CANDIDATE"
    assert "SDDM" in claims[0].statement

    stdout = (
        ot / "problems" / "PROBLEM-0001" / "experiments" / "EXP-0001" / "stdout.log"
    ).read_text()
    assert "Counterexample found" in stdout
    assert "[[ 1." in stdout


def test_harvest_counterexample_from_exp_run(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Submodularity question.", title="Nyström error")
    from opentorus.research.experiments import new_experiment

    exp = new_experiment(
        ot,
        "Counterexample search",
        command="python scripts/counterexample_nystrom.py",
        environment="python-sci",
        run_from="workspace",
    )
    results = ot / exp.path / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "stdout.txt").write_text(
        '{"trial": 0, "violation": true, "left": 1.0, "right": 2.0}\n',
        encoding="utf-8",
    )

    append_message(
        ot,
        SessionMessage(
            role="assistant",
            content="",
            metadata={
                "tool_calls": [
                    {"id": "c1", "name": "exp_run", "args": {"exp_id": exp.id}},
                ],
                "session_id": "sess2",
            },
        ),
    )
    append_message(
        ot,
        SessionMessage(
            role="tool",
            content="exit_code=0\nstatus=completed\n\nharvest me",
            metadata={"name": "exp_run", "session_id": "sess2"},
        ),
    )

    outcome = harvest_prove_session(ot, "PROBLEM-0001", session_id="sess2")
    assert outcome.harvested
    assert len(outcome.experiment_ids) == 1
    assert outcome.claim_ids == ["CLAIM-0001"]

    proofs = store.list_proof_attempts(ot, "PROBLEM-0001")
    assert len(proofs) == 1
    body = (ot / "problems" / "PROBLEM-0001" / proofs[0].body_path).read_text()
    assert "EXP-0001" in body
    assert "refuted" in body.lower()


def _run_shell_session(ot: Path, command: str, stdout: str, session_id: str) -> None:
    append_message(
        ot,
        SessionMessage(
            role="assistant",
            content="",
            metadata={
                "tool_calls": [{"id": "c1", "name": "run_shell", "args": {"command": command}}],
                "session_id": session_id,
            },
        ),
    )
    append_message(
        ot,
        SessionMessage(
            role="tool",
            content=f"exit_code=0\nstdout:\n{stdout}",
            metadata={"name": "run_shell", "session_id": session_id},
        ),
    )


def test_harvest_is_domain_agnostic_off_submodularity(tmp_path: Path) -> None:
    # A non-submodularity dossier must NOT get a fabricated SDDM/Nyström refutation.
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Does every d-polytope have polynomial diameter?", title="Hirsch")

    _run_shell_session(
        ot, "python search.py", "Counterexample found! offending object recorded.", "sess3"
    )
    outcome = harvest_prove_session(ot, "PROBLEM-0001", session_id="sess3")
    assert outcome.harvested
    claim = store.list_claims(ot, "PROBLEM-0001")[0]
    assert claim.type == "COUNTEREXAMPLE_CANDIDATE"
    # No invented domain vocabulary leaks into an unrelated problem.
    assert "SDDM" not in claim.statement and "Nyström" not in claim.statement
    proof = store.list_proof_attempts(ot, "PROBLEM-0001")[0]
    proof_body = (ot / "problems" / "PROBLEM-0001" / proof.body_path).read_text()
    assert "NOT verified" in proof_body
    assert "SDDM" not in proof_body


def test_harvest_ignores_no_counterexample(tmp_path: Path) -> None:
    # "No counterexample found" must not trigger a harvest (substring false positive).
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    store.create_dossier(ot, "Submodularity question.", title="Nyström error")
    _run_shell_session(ot, "python search.py", "No counterexample found after 10^6 trials.", "s4")
    outcome = harvest_prove_session(ot, "PROBLEM-0001", session_id="s4")
    assert not outcome.harvested
    assert not store.list_claims(ot, "PROBLEM-0001")
