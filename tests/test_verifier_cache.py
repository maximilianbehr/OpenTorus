"""An identical proof source must not be re-checked from scratch.

Experiments have had a content-addressed cache since Phase 21; verification did not,
so resubmitting the same source re-ran the backend (minutes per attempt on Lean/Coq)
and appended a duplicate ``PROOF-*`` every time. A byte-identical source also means
the model is circling, which is worth saying out loud rather than silently absorbing.
"""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.config import default_config
from opentorus.research.verifiers.base import VerificationResult
from opentorus.research.verifiers.proofs import list_proofs, submit_proof
from opentorus.research.verifiers.sympy_backend import SymPyVerifier
from opentorus.workspace import init_workspace, workspace_dir

_TRUE = json.dumps({"lhs": "sin(x)**2 + cos(x)**2", "rhs": "1", "relation": "eq"})
_FALSE = json.dumps({"lhs": "x + 1", "rhs": "x + 2", "relation": "eq"})


class _CountingVerifier:
    """Wraps the real backend so we can see whether it actually ran."""

    name = "sympy"

    def __init__(self) -> None:
        self.calls = 0
        self._inner = SymPyVerifier()

    def is_available(self) -> bool:
        return True

    def version(self) -> str | None:
        return "counting"

    def verify(self, source: str) -> VerificationResult:
        self.calls += 1
        return self._inner.verify(source)


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _submit(ot: Path, source: str, verifier, claim_id: str | None = None):
    return submit_proof(ot, default_config(), "sympy", source, claim_id=claim_id, verifier=verifier)


def test_identical_source_is_not_rechecked(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    verifier = _CountingVerifier()
    first = _submit(ot, _TRUE, verifier)
    second = _submit(ot, _TRUE, verifier)

    assert verifier.calls == 1, "the backend must not run twice for the same source"
    assert first.accepted is second.accepted is True
    assert second.id == first.id, "no duplicate artifact for an unchanged resubmission"
    assert len(list_proofs(ot)) == 1


def test_cached_answer_says_it_was_not_re_run(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    verifier = _CountingVerifier()
    _submit(ot, _TRUE, verifier)
    second = _submit(ot, _TRUE, verifier)

    assert second.cached is True
    assert "already checked" in second.output
    assert "Not re-run" in second.output
    # The model is told plainly that repeating this cannot help.
    assert "cannot change the verdict" in second.output


def test_rejections_are_cached_too(tmp_path: Path) -> None:
    """A wrong proof resubmitted unchanged is the clearest case of circling."""
    ot = _ws(tmp_path)
    verifier = _CountingVerifier()
    first = _submit(ot, _FALSE, verifier)
    assert first.accepted is False and first.inconclusive is False
    second = _submit(ot, _FALSE, verifier)
    assert verifier.calls == 1
    assert second.cached is True


def test_different_source_still_runs(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    verifier = _CountingVerifier()
    _submit(ot, _TRUE, verifier)
    _submit(ot, _FALSE, verifier)
    assert verifier.calls == 2
    assert len(list_proofs(ot)) == 2


def test_inconclusive_results_are_retried(tmp_path: Path) -> None:
    """A timeout or crash says nothing about the mathematics — try it again."""
    ot = _ws(tmp_path)

    class _Flaky:
        name = "sympy"

        def __init__(self) -> None:
            self.calls = 0

        def is_available(self) -> bool:
            return True

        def version(self) -> str | None:
            return "flaky"

        def verify(self, source: str) -> VerificationResult:
            self.calls += 1
            if self.calls == 1:
                return VerificationResult(
                    backend="sympy", accepted=False, inconclusive=True, output="timed out"
                )
            return SymPyVerifier().verify(source)

    verifier = _Flaky()
    first = _submit(ot, _TRUE, verifier)
    assert first.inconclusive is True
    second = _submit(ot, _TRUE, verifier)
    assert verifier.calls == 2, "an inconclusive result must not be cached"
    assert second.accepted is True


def test_cached_acceptance_still_links_a_new_claim(tmp_path: Path) -> None:
    from opentorus.research.graph import list_edges

    ot = _ws(tmp_path)
    verifier = _CountingVerifier()
    _submit(ot, _TRUE, verifier, claim_id="CLAIM-0001")
    _submit(ot, _TRUE, verifier, claim_id="CLAIM-0002")

    targets = {e.target_id for e in list_edges(ot) if e.relation == "validates"}
    assert {"CLAIM-0001", "CLAIM-0002"} <= targets
