"""Frozen formal benchmark with a held-out split (plan item 16).

``run_benchmark`` asks a *prover* (any callable from a :class:`BenchPrompt` to Lean
source; :func:`model_prover` wraps a provider) to prove each frozen statement of a
split, checks every candidate with the full Lean gate *against that frozen statement*
(sorry/axiom/code-execution ban, verbatim statement, unchanged preamble, identical
elaborated type), and reports pass rates.

Held-out discipline:

* a run covers one split; ``heldout`` must be asked for explicitly
  (``allow_heldout=True``) so a development loop cannot score against it by accident;
* a prompt contains exactly one problem — the one being solved — plus optional
  worked examples, which must come from ``dev`` (:func:`build_prompt` refuses a
  held-out example), so no held-out statement is ever shown as an example;
* the report carries :data:`problems.MANIFEST_SHA256`; a changed manifest is a
  different benchmark and :func:`check_manifest` refuses to run it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opentorus.errors import OpenTorusError
from opentorus.evals.formal_bench import problems as _problems
from opentorus.evals.formal_bench.problems import Split

if TYPE_CHECKING:
    from opentorus.providers.base import BaseProvider
    from opentorus.research.verifiers.backends import Lean4Backend


@dataclass(frozen=True)
class BenchItem:
    id: str
    split: Split
    informal: str
    lean: str  # the frozen file (theorem proved by `sorry`)


@dataclass(frozen=True)
class BenchPrompt:
    item_id: str
    text: str


@dataclass
class ItemOutcome:
    id: str
    split: Split
    passed: bool
    rejection: str | None = None
    inconclusive: bool = False
    detail: str = ""


@dataclass
class BenchReport:
    split: Split
    manifest_sha256: str
    outcomes: list[ItemOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        return sum(o.passed for o in self.outcomes)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def summary(self) -> str:
        lines = [
            f"formal-bench split={self.split} manifest={self.manifest_sha256[:12]} "
            f"passed {self.passed}/{self.total} ({self.pass_rate:.0%})"
        ]
        for o in self.outcomes:
            mark = "PASS" if o.passed else ("INCONCLUSIVE" if o.inconclusive else "FAIL")
            why = f" ({o.rejection})" if o.rejection and not o.passed else ""
            lines.append(f"  {o.id:8s} {mark}{why}")
        return "\n".join(lines)


def manifest_sha256() -> str:
    h = hashlib.sha256()
    for pid, split, _informal, lean in _problems.PROBLEMS:
        h.update(f"{pid}|{split}|{lean}\n".encode())
    return h.hexdigest()


def check_manifest() -> str:
    digest = manifest_sha256()
    if digest != _problems.MANIFEST_SHA256:
        raise OpenTorusError(
            "formal benchmark manifest changed (sha256 "
            f"{digest[:12]} != pinned {_problems.MANIFEST_SHA256[:12]}): a changed statement "
            "or split is a new benchmark version — update MANIFEST_SHA256 deliberately."
        )
    return digest


def load_benchmark(split: Split | None = None) -> list[BenchItem]:
    items = [BenchItem(*row) for row in _problems.PROBLEMS]
    return [i for i in items if split is None or i.split == split]


_INSTRUCTIONS = (
    "Prove the following Lean 4 + Mathlib theorem. Reply with the complete Lean file "
    "only, in one ```lean code block. Keep the header, any definitions and the theorem "
    "statement exactly as given and replace `sorry` with a proof. `sorry`, `axiom`, "
    "`native_decide` and code execution (`#eval`, `run_cmd`, …) are rejected."
)


def build_prompt(item: BenchItem, examples: list[tuple[BenchItem, str]] | None = None) -> str:
    """The prompt for one item; ``examples`` are (dev item, proof) worked examples."""
    parts = [_INSTRUCTIONS]
    for example, proof in examples or []:
        if example.split != "dev":
            raise OpenTorusError(
                f"{example.id} is a held-out item and may never be used as an example."
            )
        if example.id == item.id:
            raise OpenTorusError("an item may not be its own worked example")
        parts.append(f"Example — {example.informal}\n```lean\n{proof.strip()}\n```")
    parts.append(f"Problem — {item.informal}\n```lean\n{item.lean.strip()}\n```")
    return "\n\n".join(parts)


def extract_lean(reply: str) -> str:
    """The last fenced Lean block of a reply (or the whole reply if none)."""
    import re

    blocks = re.findall(r"```(?:lean4?|)\s*\n(.*?)```", reply, re.S)
    return (blocks[-1] if blocks else reply).strip() + "\n"


Prover = Callable[[BenchPrompt], str]


def model_prover(provider: BaseProvider) -> Prover:
    """A single-shot prover over a :class:`~opentorus.providers.base.BaseProvider`."""
    from opentorus.agent.session import SessionMessage

    def prove(prompt: BenchPrompt) -> str:
        # The prompt text is all the prover sees: one problem (plus dev examples).
        response = provider.generate([SessionMessage(role="user", content=prompt.text)])
        return extract_lean(response.content or "")

    return prove


def run_benchmark(
    prover: Prover,
    verifier: Lean4Backend,
    *,
    split: Split = "dev",
    allow_heldout: bool = False,
    examples: list[tuple[BenchItem, str]] | None = None,
    item_ids: list[str] | None = None,
) -> BenchReport:
    """Prove every item of ``split`` and verify each candidate against its frozen file."""
    from opentorus.research.verifiers import lean_rules
    from opentorus.research.verifiers.backends import FrozenSpec

    if split == "heldout" and not allow_heldout:
        raise OpenTorusError(
            "Refusing to score the held-out split without allow_heldout=True: develop "
            "against 'dev', and run 'heldout' once, deliberately."
        )
    digest = check_manifest()
    report = BenchReport(split=split, manifest_sha256=digest)
    for item in load_benchmark(split):
        if item_ids is not None and item.id not in item_ids:
            continue
        theorem = lean_rules.theorem_names(item.lean)[0]
        pristine, detail = verifier.pristine_type(item.lean)
        if pristine is None:
            report.outcomes.append(
                ItemOutcome(item.id, item.split, False, "frozen_statement_invalid", True, detail)
            )
            continue
        prompt = BenchPrompt(item_id=item.id, text=build_prompt(item, examples))
        try:
            candidate = prover(prompt)
        except Exception as exc:  # noqa: BLE001 — a prover failure is a failed item
            report.outcomes.append(
                ItemOutcome(item.id, item.split, False, "prover_error", False, str(exc))
            )
            continue
        spec = FrozenSpec(source=item.lean, theorem=theorem, pristine_type=pristine)
        result = verifier.verify_against(candidate, spec)
        report.outcomes.append(
            ItemOutcome(
                item.id,
                item.split,
                bool(result.accepted and result.statement_bound),
                result.rejection,
                bool(result.inconclusive),
                (result.output or "")[:400],
            )
        )
    return report


__all__ = [
    "BenchItem",
    "BenchPrompt",
    "BenchReport",
    "ItemOutcome",
    "build_prompt",
    "check_manifest",
    "extract_lean",
    "load_benchmark",
    "manifest_sha256",
    "model_prover",
    "run_benchmark",
]
