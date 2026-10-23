"""The frozen formal benchmark and its held-out discipline (plan item 16).

Real Lean is not installed, so the harness is exercised with the fake checker: the
point pinned here is the protocol — frozen manifest, split, statement-bound grading
through the full gate, and no held-out statement ever reaching a prompt as an example.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.evals import formal_bench
from opentorus.evals.formal_bench import (
    BenchPrompt,
    build_prompt,
    check_manifest,
    extract_lean,
    load_benchmark,
    run_benchmark,
)
from opentorus.research.verifiers import lean_rules
from opentorus.research.verifiers.backends import Lean4Backend
from support.fake_lean import fake_lean_command


def test_manifest_is_pinned_and_split_is_fixed() -> None:
    assert check_manifest() == formal_bench.problems.MANIFEST_SHA256
    dev, heldout = load_benchmark("dev"), load_benchmark("heldout")
    assert 20 <= len(dev) + len(heldout) <= 30
    assert len(heldout) >= 8
    assert {i.id for i in dev}.isdisjoint({i.id for i in heldout})


def test_every_statement_is_a_valid_frozen_file() -> None:
    for item in load_benchmark():
        assert lean_rules.frozen_objection(item.lean) is None, item.id
        assert len(lean_rules.theorem_names(item.lean)) == 1


def test_changed_manifest_refuses_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(formal_bench.problems, "MANIFEST_SHA256", "0" * 64)
    with pytest.raises(OpenTorusError, match="manifest changed"):
        check_manifest()


def test_heldout_requires_explicit_opt_in(tmp_path: Path) -> None:
    lean = Lean4Backend(fake_lean_command(tmp_path))
    with pytest.raises(OpenTorusError, match="held-out"):
        run_benchmark(lambda p: "", lean, split="heldout")


def test_heldout_items_never_become_examples() -> None:
    dev = load_benchmark("dev")
    heldout = load_benchmark("heldout")
    with pytest.raises(OpenTorusError, match="held-out"):
        build_prompt(dev[0], examples=[(heldout[0], "proof")])
    prompt = build_prompt(dev[1], examples=[(dev[0], dev[0].lean.replace("sorry", "simp"))])
    for item in heldout:
        assert item.lean.strip() not in prompt
        assert lean_rules.theorem_names(item.lean)[0] not in prompt


def test_prompts_contain_only_their_own_problem(tmp_path: Path) -> None:
    seen: list[BenchPrompt] = []

    def prover(prompt: BenchPrompt) -> str:
        seen.append(prompt)
        return ""

    run_benchmark(prover, Lean4Backend(fake_lean_command(tmp_path)), split="dev")
    heldout_names = [lean_rules.theorem_names(i.lean)[0] for i in load_benchmark("heldout")]
    assert len(seen) == len(load_benchmark("dev"))
    for prompt in seen:
        assert not any(name in prompt.text for name in heldout_names)
        others = [i for i in load_benchmark("dev") if i.id != prompt.item_id]
        names = [lean_rules.theorem_names(o.lean)[0] for o in others]
        assert not any(re.search(rf"\b{n}\b", prompt.text) for n in names)


def test_grading_goes_through_the_statement_bound_gate(tmp_path: Path) -> None:
    lean = Lean4Backend(fake_lean_command(tmp_path))
    items = {i.id: i for i in load_benchmark("dev")}

    def prover(prompt: BenchPrompt) -> str:
        item = items[prompt.item_id]
        if prompt.item_id == "fb-001":
            return item.lean.replace("sorry", "simp")  # a proof (fake Lean accepts)
        if prompt.item_id == "fb-002":
            return item.lean  # still `sorry`
        if prompt.item_id == "fb-003":
            return "import Mathlib\n\ntheorem fb_sq_nonneg : True := trivial\n"  # wrong theorem
        if prompt.item_id == "fb-004":
            return item.lean.replace("sorry", "native_decide")
        return "no lean here"

    report = run_benchmark(
        prover, lean, split="dev", item_ids=["fb-001", "fb-002", "fb-003", "fb-004", "fb-005"]
    )
    by_id = {o.id: o for o in report.outcomes}
    assert by_id["fb-001"].passed is True
    assert by_id["fb-002"].rejection == "sorry"
    assert by_id["fb-003"].rejection == "statement_mismatch"
    assert by_id["fb-004"].rejection == "forbidden_token"
    assert by_id["fb-005"].passed is False
    assert report.passed == 1 and report.total == 5
    assert "passed 1/5" in report.summary()


def test_heldout_run_with_opt_in(tmp_path: Path) -> None:
    lean = Lean4Backend(fake_lean_command(tmp_path))
    items = {i.id: i for i in load_benchmark("heldout")}
    report = run_benchmark(
        lambda p: items[p.item_id].lean.replace("sorry", "simp"),
        lean,
        split="heldout",
        allow_heldout=True,
    )
    assert report.split == "heldout"
    assert report.passed == report.total == len(items)


def test_extract_lean_takes_the_last_block() -> None:
    reply = "Here:\n```lean\nfirst\n```\nfixed:\n```lean4\ntheorem t : True := trivial\n```"
    assert extract_lean(reply) == "theorem t : True := trivial\n"
