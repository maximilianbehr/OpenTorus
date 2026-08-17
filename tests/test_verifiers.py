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
    """ "<=" between matrices has no single meaning; picking one would be a guess."""
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


def test_lambda_is_named_as_the_problem_and_a_substitute_is_offered() -> None:
    """sympify parses through Python, so `lambda` cannot be a symbol — and λ is *the*
    name for an eigenvalue.

    A Balan-Wang run submitted `{"lhs": "(3 - sqrt(5))/2", "rhs": "lambda"}` and got
    "Sympify of expression 'could not parse 'lambda'' failed, because of exception being
    raised: SyntaxError", which names neither the offending word nor a way around it.
    The model abandoned the symbolic statement and submitted a closed arithmetic one.
    """
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify(
        '{"lhs": "(3 - sqrt(5))/2", "rhs": "lambda", "relation": "eq", "vars": ["lambda"]}'
    )
    assert result.inconclusive  # a naming problem is not a mathematical rejection
    assert not result.accepted
    assert "'lambda' cannot be a symbol name" in result.output
    assert "reserved word" in result.output
    assert "'lambda' -> 'lam'" in result.output


def test_a_legal_symbol_name_is_untouched() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify(
        '{"lhs": "lam**2 - 3*lam + 1", "rhs": "lam**2 - 3*lam + 1",'
        ' "relation": "eq", "vars": ["lam"]}'
    )
    assert result.accepted


def test_a_malformed_certificate_shows_the_offending_text() -> None:
    """ "column 3553 (char 3552)" is unusable for a 3.5 KB single-line certificate.

    Seen on a Hadamard submission that spelled out sixteen orthogonality conditions
    inline: the model was told where the error was in characters, which it cannot count.
    """
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    source = '{"lhs": "' + "x+1+" * 400 + 'x", "rhs" "0", "relation": "eq"}'
    result = SymPyVerifier().verify(source)

    assert result.inconclusive
    assert "not valid JSON" in result.output
    # The neighbourhood of the fault is quoted, with a caret under it.
    assert '"rhs" "0"' in result.output
    assert "^" in result.output


def test_a_well_formed_certificate_is_unaffected() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify('{"lhs": "2*n", "rhs": "n+n", "relation": "eq", "vars": ["n"]}')
    assert result.accepted


def test_min_and_max_are_available_to_the_interval_backend() -> None:
    """ "the smallest of these is at most X" is the natural shape for this backend.

    A Balan-Wang run submitted min(1-abs(cos(t1)), 1-abs(cos(t2)), 1-abs(cos(t2-t1)))
    and was refused as unparseable; it had already been refused the same shape in sympy,
    where an order relation on a Min never has a constant-sign difference. It then gave
    up and submitted `0.5**2 - 2*0.5 + 0.75 = 0`. min/max over intervals are exact.
    """
    from opentorus.research.verifiers.interval import IntervalVerifier

    result = IntervalVerifier().verify(
        '{"variables": {"x": [0, 1]}, "expression": "min(x, 1-x)", "relation": "<=", "bound": 1.5}'
    )
    # It parses and yields a rigorous enclosure instead of a format refusal. The
    # enclosure is sound, not tight: interval arithmetic treats x and 1-x as
    # independent, so min encloses to [0, 1] rather than the true range [0, 0.5].
    assert "not available here" not in result.output
    assert "enclosure" in result.output
    assert result.accepted, result.output


def test_an_unavailable_function_is_named() -> None:
    """With three nested calls, "only sqrt/exp/log/… are allowed" leaves it guessing."""
    from opentorus.research.verifiers.interval import IntervalVerifier

    result = IntervalVerifier().verify(
        '{"variables": {"x": [0, 1]}, "expression": "gamma(x)", "relation": "<=", "bound": 1}'
    )
    assert not result.accepted
    assert "'gamma' is not available here" in result.output
    assert "min/max" in result.output


def test_a_symbolic_inequality_with_a_determinate_sign_is_decided() -> None:
    """Checking only `is_number` refused every provable symbolic inequality.

    An sos-coloring run submitted `x**2 >= 0` and was told this backend "decides
    identities and constant comparisons, not universally quantified inequalities" — but
    once the variable is real, sympy settles it outright, along with exp(x) > 0,
    -x**2 <= 0 and |x| >= 0, which are exactly what a lemma step reduces to.
    """
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    v = SymPyVerifier()
    for lhs, rel in (("x**2", "ge"), ("exp(x)", "gt"), ("-x**2", "le"), ("Abs(x)", "ge")):
        result = v.verify(
            f'{{"lhs": "{lhs}", "rhs": "0", "relation": "{rel}", "vars": {{"x": "real"}}}}'
        )
        assert result.accepted, (lhs, rel, result.output)
        assert result.general is True


def test_a_false_symbolic_inequality_is_rejected_not_accepted() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify(
        '{"lhs": "-x**2", "rhs": "0", "relation": "gt", "vars": {"x": "real"}}'
    )
    assert not result.accepted and not result.inconclusive
    assert "never satisfies" in result.output


def test_an_undeclared_symbol_is_told_to_declare_its_domain() -> None:
    """The run that hit this declared `vars: ["x"]`, which leaves x complex.

    Refusing was formally right — x**2 >= 0 is not a statement about complex x — but the
    message said the backend cannot do quantified inequalities at all, which is wrong and
    sent the model away from the one repair that works.
    """
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify('{"lhs": "x**2", "rhs": "0", "relation": "ge", "vars": ["x"]}')
    assert result.inconclusive
    assert "carries no domain" in result.output
    assert '"real"' in result.output


def test_a_genuinely_undecidable_inequality_keeps_the_routes_message() -> None:
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    result = SymPyVerifier().verify(
        '{"lhs": "cos(x)", "rhs": "0", "relation": "ge", "vars": {"x": "real"}}'
    )
    assert result.inconclusive
    assert "Routes that do work" in result.output
