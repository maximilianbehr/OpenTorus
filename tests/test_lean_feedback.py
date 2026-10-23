"""Structured Lean feedback, proof-state continuation, and the tactic suite (items 13, 14).

* checker output is classified (harness ``classify_error`` rules) into a compact
  summary — first error, unsolved goal, repairable — which ``proof_submit`` returns
  instead of a raw dump, while the raw output stays in the PROOF-* record;
* a branch whose previous Lean candidate failed is told to repair it (source +
  feedback in the prompt), with a fresh root attempt every N-th time;
* a candidate refused only for ``sorry`` gets a tactic-suite pass, and the closed
  splice is accepted only through the full gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.campaign.workers import formalizer
from opentorus.config import default_config
from opentorus.research.verifiers.backends import Lean4Backend
from opentorus.research.verifiers.diagnostics import classify_error, render, summarize
from opentorus.research.verifiers.proofs import list_proofs, submit_proof
from opentorus.research.verifiers.tactic_suite import (
    hollow_sorries,
    run_suite,
    sorry_spans,
    with_heartbeats,
)
from opentorus.tools.base import ToolCall
from opentorus.tools.research import ProofSubmitTool
from opentorus.workspace import init_workspace, workspace_dir
from support.fake_lean import fake_lean_command

LEAN_OUTPUT = """proof.lean:3:2: error: unsolved goals
n : Nat
⊢ n + 0 = n
proof.lean:7:10: error: unknown identifier 'Nat.foo'
proof.lean:9:4: warning: declaration uses 'sorry'
proof.lean:12:2: error: linarith failed to find a contradiction
"""


# --- item 13: structured feedback ------------------------------------------------


@pytest.mark.parametrize(
    ("message", "cls"),
    [
        ("(deterministic) timeout at `whnf`, maximum number of heartbeats", "timeout"),
        ("unexpected token 'at'; expected command", "syntax"),
        ("unsolved goals\n⊢ False", "unsolved_goals"),
        ("unknown identifier 'foo'", "unknown_identifier"),
        ("unknown constant 'Nat.bar'", "unknown_identifier"),
        ("no goals to be solved", "no_goals"),
        ("failed to synthesize\n  Fintype α", "synth_failed"),
        ("tactic 'rewrite' failed, did not find instance of the pattern", "tactic_misapplied"),
        ("Did not find an occurrence of the pattern", "rewrite_failed"),
        ("linarith failed to find a contradiction", "automation_failed"),
        ("type mismatch\n  h\nhas type", "type_mismatch"),
        ("something entirely new", "other"),
    ],
)
def test_error_classes(message: str, cls: str) -> None:
    assert classify_error(message) == cls


def test_summary_has_first_error_goal_and_repairability() -> None:
    diag = summarize("lean4", LEAN_OUTPUT)
    assert diag is not None
    assert diag["error_count"] == 3
    assert diag["classes"] == ["unsolved_goals", "unknown_identifier", "automation_failed"]
    assert diag["first_error"]["line"] == 3
    assert diag["first_error"]["class"] == "unsolved_goals"
    assert "⊢ n + 0 = n" in diag["unsolved_goal"]
    assert diag["sorry_warnings"] == 1
    assert diag["repairable"] is True


def test_many_errors_are_not_repairable() -> None:
    output = "\n".join(f"f.lean:{i}:0: error: unknown identifier 'x{i}'" for i in range(1, 6))
    diag = summarize("lean4", output)
    assert diag is not None and diag["repairable"] is False
    assert "restructuring" in render(diag)


def test_summary_is_deterministic() -> None:
    assert summarize("lean4", LEAN_OUTPUT) == summarize("lean4", LEAN_OUTPUT)


def test_coq_errors_are_parsed() -> None:
    out = (
        'File "p.v", line 4, characters 2-10:\n'
        "Error: The reference foo was not found in the current environment.\n"
    )
    diag = summarize("coq", out)
    assert diag is not None
    assert diag["first_error"]["line"] == 4
    assert diag["classes"] == ["unknown_identifier"]


def test_proof_submit_returns_summary_not_dump_and_keeps_raw(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    lean = Lean4Backend(fake_lean_command(tmp_path))
    tool = ProofSubmitTool(ot, default_config(), resolver=lambda _n: lean)
    padding = "\n".join(f"-- filler line {i} " + "x" * 80 for i in range(80))
    source = f"{padding}\ntheorem t (n : Nat) : n + 0 = n := by\n  FAKE_UNSOLVED"
    result = tool.run(ToolCall(name="proof_submit", args={"backend": "lean4", "source": source}))
    assert result.ok is False
    assert "unsolved_goals" in result.content
    assert "Unsolved goal" in result.content and "⊢ n + 0 = n" in result.content
    assert len(result.content) < 2500
    proof = list_proofs(ot)[-1]
    assert "unsolved goals" in proof.output  # raw output preserved in the artifact
    assert proof.diagnostics and proof.diagnostics["error_count"] == 1


# --- item 14: tactic suite --------------------------------------------------------

SKELETON = """import Mathlib

theorem t (n : Nat) : n + 0 = n := by
  -- closes: omega
  sorry
"""


def test_sorry_spans_skip_comments_and_identifiers() -> None:
    src = "-- sorry\ntheorem t : True := by\n  sorry -- sorry\ndef sorryish := 1"
    assert len(sorry_spans(src)) == 1


def test_heartbeat_option_goes_after_imports() -> None:
    out = with_heartbeats("import Mathlib\nimport Aesop\n\ntheorem t : True := trivial")
    lines = out.splitlines()
    assert lines[2] == "set_option maxHeartbeats 100000"


def test_tactic_suite_closes_the_sorry(tmp_path: Path) -> None:
    lean = Lean4Backend(fake_lean_command(tmp_path))
    suite = run_suite(lean, SKELETON)
    assert suite.attempted is True
    assert suite.spliced is not None
    assert "omega" in suite.spliced and "sorry" not in suite.spliced.split("closes")[1]
    # The splice is accepted only by the full gate.
    assert lean.verify(suite.spliced).accepted is True


def test_tactic_suite_skips_candidates_with_real_errors(tmp_path: Path) -> None:
    lean = Lean4Backend(fake_lean_command(tmp_path))
    suite = run_suite(lean, SKELETON.replace("sorry", "sorry\n  FAKE_ERROR"))
    assert suite.attempted is False
    assert "errors besides" in suite.reason


def test_tactic_suite_reports_unclosable(tmp_path: Path) -> None:
    lean = Lean4Backend(fake_lean_command(tmp_path))
    suite = run_suite(lean, SKELETON.replace("omega", "ring_nf"))
    assert suite.spliced is None
    assert "closed 0 of 1" in suite.reason


def test_hollow_have_is_detected() -> None:
    src = "theorem t (n : Nat) : n + 0 = n := by\n  have h : n + 0 = n := sorry\n  exact h\n"
    assert hollow_sorries(src) == [0]
    honest = "theorem t (n : Nat) : n + 0 = n := by\n  have h : 0 + n = n := sorry\n  omega\n"
    assert hollow_sorries(honest) == []


# --- item 14: formalizer continuation ----------------------------------------------


def _ctx(branch_ids: tuple[str, ...]):  # noqa: ANN202
    from opentorus.campaign.models import (
        CampaignMode,
        NormalizedProblem,
        WorkerContext,
        WorkerRole,
    )

    return WorkerContext(
        campaign_id="CAMPAIGN-0001",
        branch_id="BRANCH-0001",
        work_item_id="WI-0001",
        role=WorkerRole.formalizer,
        task_class="formalize",
        mode=list(CampaignMode)[0],
        root_problem=NormalizedProblem(problem_id="PROBLEM-0001", statement="n + 0 = n"),
        branch_artifact_ids=branch_ids,
    )


def test_continuation_repairs_then_restarts(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    lean = Lean4Backend(fake_lean_command(tmp_path))
    ids: list[str] = []
    assert formalizer.continuation(_ctx(()), ot) == ("root", None)
    first = submit_proof(
        ot,
        default_config(),
        "lean4",
        "theorem t (n : Nat) : n + 0 = n := by\n  FAKE_UNSOLVED",
        verifier=lean,
    )
    ids.append(first.id)
    mode, prev = formalizer.continuation(_ctx(tuple(ids)), ot)
    assert mode == "repair" and prev is not None and prev.id == first.id
    prompt = formalizer._prompt(_ctx(tuple(ids)), ["lean4"], ot_dir=ot, mode=mode, previous=prev)
    assert "REPAIR FIRST" in prompt and "FAKE_UNSOLVED" in prompt
    assert "Unsolved goal" in prompt
    for i in range(2):
        again = submit_proof(
            ot,
            default_config(),
            "lean4",
            f"theorem t (n : Nat) : n + 0 = n := by\n  FAKE_UNSOLVED -- {i}",
            verifier=lean,
        )
        ids.append(again.id)
    # 3 prior attempts → the 4th is a fresh root attempt.
    mode, _prev = formalizer.continuation(_ctx(tuple(ids)), ot)
    assert mode == "fresh_root"
    prompt = formalizer._prompt(_ctx(tuple(ids)), ["lean4"], ot_dir=ot, mode=mode, previous=_prev)
    assert "FRESH ROOT ATTEMPT" in prompt


def test_formalizer_tactic_suite_pass_resubmits_through_the_gate(tmp_path: Path) -> None:
    from opentorus.campaign.workers.base import WorkerRuntime

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.tools.verifiers.lean = True
    config.tools.verifiers.lean_command = fake_lean_command(tmp_path)
    refused = submit_proof(ot, config, "lean4", SKELETON)
    assert refused.rejection == "sorry"
    rt = WorkerRuntime(root=tmp_path, ot_dir=ot, config=config, pool=None)  # type: ignore[arg-type]
    new = formalizer.tactic_suite_pass(rt, [refused])
    assert len(new) == 1
    assert new[0].accepted is True
    assert "omega" in (ot / new[0].source_path).read_text(encoding="utf-8")
    config.tools.verifiers.lean_tactic_suite = False
    assert formalizer.tactic_suite_pass(rt, [refused]) == []
