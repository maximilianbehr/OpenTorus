"""Tests for the random_nla scan fixes: single-primary refine, title clip, template guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.dossier import store
from opentorus.tools.base import ToolCall
from opentorus.tools.research import ProofWriteTool
from opentorus.workspace import init_workspace, workspace_dir


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    return base, store.create_dossier(base, "Prove or refute: X holds for all n.").id


def _write(tool: ProofWriteTool, pid: str, title: str, gap: bool) -> object:
    body = "We argue X holds via a direct estimate that bounds the residual. " + (
        "Step one is complete. [GAP-1] justify the constant." if gap else "All steps justified."
    )
    return tool.run(
        ToolCall(
            id="1",
            name="proof_write",
            args={
                "problem_id": pid,
                "title": title,
                "theorem": "X holds for all n.",
                "main_proof": body,
                "scope": "primary",
            },
        )
    )


def test_proof_write_refines_single_primary_in_place(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    tool = ProofWriteTool(base)
    r1 = _write(tool, pid, "First primary sketch", gap=True)
    r2 = _write(tool, pid, "Refined primary sketch", gap=False)
    assert r1.ok and r2.ok
    # Both writes resolve to the SAME single primary proof; the second refined it.
    primaries = [p for p in store.list_proof_attempts(base, pid) if p.scope == "primary"]
    assert len(primaries) == 1
    assert "refined" in r2.content.lower()
    # The refinement replaced the body in place: the latest body is the gap-free one,
    # and the earlier [GAP-1] marker is gone.
    body = (base / "problems" / pid / primaries[0].body_path).read_text()
    assert "All steps justified" in body
    assert "[GAP-1]" not in body


def test_proof_write_accepts_lemmas_as_array(tmp_path: Path) -> None:
    # Models often pass structured fields as arrays; the tool must coerce, not reject
    # with "Argument 'lemmas' must be a string".
    from opentorus.tools.base import validate_tool_args

    base, pid = _problem(tmp_path)
    tool = ProofWriteTool(base)
    args = {
        "problem_id": pid,
        "title": "Sketch with list lemmas",
        "theorem": "X holds for all n.",
        "main_proof": "We bound the residual directly; the estimate gives the result.",
        "lemmas": ["Lemma A: the residual is monotone.", "Lemma B: the bound is tight."],
        "scope": "primary",
    }
    # The arg validator must not reject the array-typed field.
    assert validate_tool_args(tool.input_schema, args) is None
    result = tool.run(ToolCall(id="1", name="proof_write", args=args))
    assert result.ok
    proofs = store.list_proof_attempts(base, pid)
    body = (base / "problems" / pid / proofs[0].body_path).read_text()
    assert "Lemma A" in body and "Lemma B" in body


def test_clip_title_truncates_at_word_boundary() -> None:
    from opentorus.cli.problem import _clip_title

    long = "Problem: Landmark sampling for the randomized Nyström approximation of kernel matrices"
    clipped = _clip_title(long)
    assert len(clipped) <= 80
    assert clipped.endswith("…")
    assert not clipped.endswith("kernel ma…")  # never mid-word
    assert "kernel" not in clipped or clipped.rstrip("…").split()[-1] != "ker"


def test_write_guard_blocks_managed_dossier_artifacts(tmp_path: Path) -> None:
    # A raw write into a dossier's tool-managed artifacts is refused (this is how the
    # live agent clobbered its own PROOF-0001.md); free-form notes stay writable.
    from opentorus.tools.filesystem import write_file

    base, pid = _problem(tmp_path)  # noqa: F841 - ensures the dossier exists
    root = tmp_path
    for managed in (
        f".opentorus/problems/{pid}/proof_attempts/PROOF-0001.md",
        f".opentorus/problems/{pid}/claims.jsonl",
        f".opentorus/problems/{pid}/report.md",
        f".opentorus/problems/{pid}/evidence/E.json",
    ):
        with pytest.raises(OpenTorusError):
            write_file(root, managed, "clobber")
    # A free-form note in the dossier is still allowed.
    written = write_file(root, f".opentorus/problems/{pid}/notes.md", "scratch")
    assert written.read_text() == "scratch"


def test_unmodified_counterexample_template_cannot_back_a_claim(tmp_path: Path) -> None:
    from opentorus.research.claims import new_claim
    from opentorus.research.evidence import add_evidence
    from opentorus.research.experiments import new_experiment, run_experiment

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    claim = new_claim(ot, "Some conjecture P(n).")
    # Create the counterexample-search experiment but DON'T edit the predicate.
    exp = new_experiment(ot, "search", template="counterexample_search")
    run_experiment(ot, exp.id)
    with pytest.raises(OpenTorusError):
        add_evidence(ot, claim.id, source_type="experiment", source_id=exp.id, direction="supports")
