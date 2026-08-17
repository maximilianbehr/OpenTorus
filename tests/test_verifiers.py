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


def test_interval_accepts_the_shapes_models_actually_send() -> None:
    # Observed live: a model submitted {"variables": ["x"], "domain": {"x": [1,1]}}
    # twice in a row, after being shown a valid example — splitting names from
    # boxes is a reasonable layout the documented form did not cover.
    import json

    from opentorus.research.verifiers.interval import IntervalVerifier

    v = IntervalVerifier()
    base = {"expression": "x*x", "relation": ">=", "bound": 0.0}
    for spec in (
        {"variables": {"x": [1.0, 2.0]}},  # documented form
        {"variables": ["x"], "domain": {"x": [1.0, 2.0]}},  # names + separate boxes
        {"variables": ["x"], "box": {"x": [1.0, 2.0]}},
        {"domain": {"x": [1.0, 2.0]}},  # boxes only, no 'variables' key
        {"variables": [["x", 1.0, 2.0]]},  # list of triples
        {"variables": [["x", [1.0, 2.0]]]},  # list of name/box pairs
    ):
        result = v.verify(json.dumps({**base, **spec}))
        assert result.accepted is True, spec

    # No boxes anywhere is still an honest rejection that names the expected shape.
    missing = v.verify(json.dumps({**base, "variables": ["x"]}))
    assert missing.accepted is False
    assert "name -> [lo, hi]" in missing.output


def test_sympy_inequality_in_free_variables_names_the_routes_that_work() -> None:
    # Observed live (tensor-concentration): the model submitted a correct power-mean
    # inequality in free variables. sympy cannot decide a universally quantified
    # inequality by simplification, which is honest — but the old message said only
    # "needs a constant-sign difference", leaving a true statement with no next step.
    import json

    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify(
        json.dumps(
            {
                "lhs": "x1**2 + x2**2",
                "rhs": "2**(1 - 2/4) * (x1**4 + x2**4)**(2/4)",
                "relation": "le",
                "vars": ["x1", "x2"],
            }
        )
    )
    assert result.accepted is False
    assert result.inconclusive is True  # not a refutation of the mathematics
    assert "x1" in result.output and "x2" in result.output  # names what is still free
    for route in ("interval", "smt", "relation='eq'", "[GAP-n]"):
        assert route in result.output, route

    # A constant comparison is still decided, not deflected into the advice branch.
    decided = SymPyVerifier().verify(json.dumps({"lhs": "2**10", "rhs": "1000", "relation": "gt"}))
    assert decided.accepted is True


def test_a_closed_arithmetic_certificate_supports_rather_than_validates(tmp_path: Path) -> None:
    """Verifying "1+2 = 3" does not validate a claim that quantifies over anything.

    Real runs submitted exactly that against "for n=3, max A >= 4", and
    "2**(4-2) + 1 = 5" against the Happy Ending conjecture; seven of eleven accepted
    proofs in one sweep were closed arithmetic. Claim *status* was never promoted — that
    invariant held — but the graph asserted a relationship the artifact does not carry.
    """
    ot = _ot(tmp_path)
    from opentorus.research.claims import new_claim

    claim = new_claim(ot, "For n=3, any set with distinct subset sums satisfies max A >= 4.")
    proof = submit_proof(
        ot,
        default_config(),
        "sympy",
        '{"lhs": "1+2", "rhs": "3", "relation": "eq", "vars": []}',
        claim_id=claim.id,
    )

    assert proof.accepted
    edges = [e for e in related(ot, proof.id) if e.target_id == claim.id]
    assert len(edges) == 1
    assert edges[0].relation == "supports"
    assert "closed arithmetic statement" in edges[0].rationale
    assert "not the claim in general" in edges[0].rationale


def test_a_certificate_with_free_variables_still_validates(tmp_path: Path) -> None:
    """The Erdős–Straus identities a run produced are general, and must keep their edge."""
    ot = _ot(tmp_path)
    from opentorus.research.claims import new_claim

    claim = new_claim(ot, "For even n >= 2 the Erdős–Straus conjecture holds.")
    proof = submit_proof(
        ot,
        default_config(),
        "sympy",
        '{"lhs": "4/n", "rhs": "1/(n/2) + 1/(n/2 + 1) + 1/((n/2)*(n/2 + 1))",'
        ' "relation": "eq", "vars": ["n"]}',
        claim_id=claim.id,
    )

    assert proof.accepted
    edges = [e for e in related(ot, proof.id) if e.target_id == claim.id]
    assert [e.relation for e in edges] == ["validates"]


_H4 = "Matrix([[1, 1, 1, 1], [1, -1, 1, -1], [1, 1, -1, -1], [1, -1, -1, 1]])"


def test_a_correct_matrix_identity_is_not_called_false() -> None:
    """A sympy Matrix never equals the integer 0, so `diff == 0` was False for a zero matrix.

    Observed on the Hadamard dossier: H·Hᵀ = 4I was rejected twice as "the identity does
    not hold", with the zero matrix printed inside the rejection. The run shows what that
    costs — the model abandoned the real identity and submitted "1+1 = 2" instead, which
    the backend happily accepted.
    """
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify(
        f'{{"lhs": "{_H4} * {_H4}.T", "rhs": "4 * eye(4)", "relation": "eq", "vars": []}}'
    )
    assert result.accepted, result.output
    assert "zero matrix" in result.output


def test_a_wrong_matrix_identity_is_still_rejected() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify(
        f'{{"lhs": "{_H4} * {_H4}.T", "rhs": "5 * eye(4)", "relation": "eq", "vars": []}}'
    )
    assert not result.accepted
    assert not result.inconclusive


def test_an_order_relation_between_matrices_is_inconclusive_not_decided() -> None:
    """"<=" between matrices has no single meaning; picking one would be a guess."""
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify(
        f'{{"lhs": "{_H4}", "rhs": "eye(4)", "relation": "le", "vars": []}}'
    )
    assert result.inconclusive
    assert not result.accepted
    assert "ambiguous" in result.output


def test_generality_is_reported_for_scalars_and_matrices() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    v = SymPyVerifier()
    assert v.verify('{"lhs": "1+2", "rhs": "3", "relation": "eq", "vars": []}').general is False
    assert v.verify('{"lhs": "2*n", "rhs": "n+n", "relation": "eq", "vars": ["n"]}').general is True
