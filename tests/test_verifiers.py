"""Tests for formal verification backends (Milestone 51).

A trivial valid lemma is accepted via a stub backend; an invalid one is rejected;
and the absence of a backend is reported honestly. No real Lean/Coq is required.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.research.graph import related
from opentorus.research.verifiers import submit_proof
from opentorus.research.verifiers.base import VerificationResult
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


class StubVerifier:
    """A fake backend that accepts iff the source contains 'VALID'."""

    name = "stub"

    def __init__(self, available: bool = True) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def version(self) -> str | None:
        return "stub-1.0" if self._available else None

    def verify(self, source: str) -> VerificationResult:
        if not self._available:
            return VerificationResult(
                backend=self.name, accepted=False, available=False, output="not installed"
            )
        ok = "VALID" in source
        return VerificationResult(
            backend=self.name,
            backend_version="stub-1.0",
            accepted=ok,
            output="QED" if ok else "type error",
        )


def test_valid_lemma_accepted(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    proof = submit_proof(
        ot, default_config(), "lean4", "theorem t : VALID := rfl", verifier=StubVerifier()
    )
    assert proof.accepted is True
    assert proof.backend_version == "stub-1.0"
    assert (ot / proof.source_path).is_file()


def test_invalid_lemma_rejected(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    proof = submit_proof(
        ot, default_config(), "lean4", "theorem t : nonsense", verifier=StubVerifier()
    )
    assert proof.accepted is False
    assert "type error" in proof.output


def test_absent_backend_reported_honestly(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    proof = submit_proof(
        ot,
        default_config(),
        "lean4",
        "theorem t : VALID := rfl",
        verifier=StubVerifier(available=False),
    )
    assert proof.available is False
    assert proof.accepted is False


def test_unconfigured_backend_raises(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    # Default config has lean/coq disabled, so no verifier resolves.
    try:
        submit_proof(ot, default_config(), "lean4", "anything")
        raise AssertionError("expected an error for an unconfigured backend")
    except Exception as exc:  # noqa: BLE001
        assert "not enabled" in str(exc) or "unavailable" in str(exc)


def test_accepted_proof_links_claim_in_graph(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    from opentorus.research.claims import new_claim

    claim = new_claim(ot, "VALID lemma holds.")
    proof = submit_proof(
        ot,
        default_config(),
        "lean4",
        "theorem t : VALID := rfl",
        claim_id=claim.id,
        verifier=StubVerifier(),
    )
    edges = related(ot, proof.id)
    assert any(e.relation == "validates" and e.target_id == claim.id for e in edges)


def test_enabled_backend_resolves_from_config(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    config = default_config()
    config.tools.verifiers.lean = True
    config.tools.verifiers.lean_command = "definitely-not-installed-lean-xyz"
    # Backend is enabled but not installed → honest unavailable, not a crash.
    proof = submit_proof(ot, config, "lean4", "theorem t : VALID := rfl")
    assert proof.available is False
    assert proof.accepted is False


def test_verify_tempfile_readable_by_other_uids(tmp_path: Path) -> None:
    # Containerized checkers (Docker Coq fallback) run as a different uid: with the
    # default 0700 tempdir every submission failed with "Can't find file". The
    # backend must make the dir/file world-readable (proof sources are not secrets —
    # they are persisted verbatim in the PROOF-* artifact).
    from opentorus.research.verifiers.backends import Lean4Backend

    backend = Lean4Backend('sh -c \'stat -c "%a" "$(dirname "$1")"; stat -c "%a" "$1"\' sh')
    result = backend.verify("theorem t : VALID := rfl")
    assert result.available is True
    assert "755" in result.output  # tempdir traversable by the container uid
    assert "644" in result.output  # source readable by the container uid


def test_sympy_accepts_list_and_alias_variable_specs() -> None:
    # Benchmark finding: models write `vars` as a bare list of names, or use the
    # `variables` alias. Both used to raise AttributeError inside the backend,
    # which reached the model as an internal traceback (19 lost submissions).
    import json

    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    v = SymPyVerifier()
    identity = {"lhs": "(a+b)*(a-b)", "rhs": "a*a - b*b", "relation": "eq"}

    for spec in (
        {"vars": {"a": "real", "b": "real"}},  # documented object form
        {"vars": ["a", "b"]},  # bare list of names
        {"variables": ["a", "b"]},  # alias, list
        {"variables": {"a": "real"}},  # alias, object
        {},  # omitted entirely
    ):
        result = v.verify(json.dumps({**identity, **spec}))
        assert result.accepted is True, spec

    # A nonsense spec must not raise: it degrades to plain symbols and still verifies.
    assert v.verify(json.dumps({**identity, "vars": "a,b"})).accepted is True


def test_sympy_never_raises_on_malformed_certificates() -> None:
    import json

    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    v = SymPyVerifier()
    for bad in ("not json", json.dumps([1, 2]), json.dumps({"lhs": "a"})):
        result = v.verify(bad)  # must return, never raise
        assert result.accepted is False
        assert result.output
