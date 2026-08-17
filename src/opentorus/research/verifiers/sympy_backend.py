"""Symbolic identity/inequality verifier backed by sympy.

The most common machine-math claim is a plain symbolic identity or inequality, for
which Lean/Coq/SMT are heavyweight and an interval enclosure does not apply. This
backend discharges such a claim from a small JSON certificate::

    {"lhs": "sin(x)**2 + cos(x)**2", "rhs": "1", "relation": "eq",
     "assumptions": ["x>0"], "vars": {"x": "real"}}

It is honest by construction: an equality is ``accepted`` only when
``simplify(lhs - rhs) == 0``; an inequality only when the simplified difference has
a provably constant sign. Anything it cannot settle symbolically is reported
``inconclusive`` (``accepted=False``) — never a fabricated proof. sympy is a core
dependency, so the backend is always available.
"""

from __future__ import annotations

import json
import keyword
import re

from opentorus.research.verifiers.base import VerificationResult

_RELATIONS = {"eq", "ne", "le", "lt", "ge", "gt"}

# sympify parses through Python, so a Python keyword cannot be a symbol name — and
# ``lambda`` is the standard name for an eigenvalue. A Balan-Wang run wrote
# ``{"lhs": "(3 - sqrt(5))/2", "rhs": "lambda"}`` and got back "Sympify of expression
# 'could not parse 'lambda'' failed, because of exception being raised: SyntaxError",
# which names neither the offending word nor a way around it. The model then abandoned
# the symbolic statement and submitted a closed arithmetic one instead — the same
# degradation the Hadamard matrix bug produced. Suggest the conventional stand-ins.
_KEYWORD_SUBSTITUTES = {
    "lambda": "lam",
    "in": "in_",
    "is": "is_",
    "not": "not_",
    "or": "or_",
    "and": "and_",
    "if": "if_",
    "as": "as_",
    "del": "del_",
    "from": "from_",
    "import": "import_",
    "class": "class_",
    "def": "def_",
    "return": "return_",
    "None": "none_",
    "True": "true_",
    "False": "false_",
}
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def _reserved_identifiers(expression_text: str, spec: object) -> list[str]:
    """Python keywords used as symbol names, in the expressions or the variable spec."""
    names = set(_IDENTIFIER.findall(expression_text))
    if isinstance(spec, dict):
        names |= {str(k) for k in spec}
    elif isinstance(spec, (list, tuple, set)):
        names |= {str(v) for v in spec}
    return sorted(n for n in names if keyword.iskeyword(n))


def _reserved_message(reserved: list[str]) -> str:
    pairs = ", ".join(f"'{n}' -> '{_KEYWORD_SUBSTITUTES.get(n, n + '_')}'" for n in reserved)
    listed = ", ".join(f"'{n}'" for n in reserved)
    return (
        f"{listed} cannot be a symbol name: this backend parses expressions through "
        f"Python, where it is a reserved word. Rename and resubmit — {pairs} — keeping "
        "the same mathematics; the name is arbitrary to the check."
    )


class SymPyVerifier:
    """A symbolic-algebra verifier exposed through the verifier protocol."""

    name = "sympy"

    def is_available(self) -> bool:
        try:
            import sympy  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str | None:
        try:
            import sympy
        except ImportError:
            return None
        return getattr(sympy, "__version__", None)

    def verify(self, source: str) -> VerificationResult:
        if not self.is_available():
            return VerificationResult(
                backend=self.name,
                accepted=False,
                available=False,
                output="sympy is not installed; symbolic verification unavailable.",
            )
        import sympy as sp

        try:
            cert = json.loads(source)
        except json.JSONDecodeError as exc:
            return self._inconclusive(f"certificate is not valid JSON: {exc}")
        if not isinstance(cert, dict) or "lhs" not in cert or "rhs" not in cert:
            return self._inconclusive("certificate must be an object with 'lhs' and 'rhs'.")
        relation = str(cert.get("relation", "eq")).lower()
        if relation not in _RELATIONS:
            return self._inconclusive(f"unknown relation '{relation}'; valid: {sorted(_RELATIONS)}")

        # Models write the variable spec as `vars` or `variables`, and as either a
        # name -> kind object or a bare list of names. All four shapes are accepted:
        # a rejected certificate must teach the format, never crash (a list used to
        # raise AttributeError, which reached the model as an internal traceback).
        spec = cert.get("vars")
        if spec is None:
            spec = cert.get("variables")
        reserved = _reserved_identifiers(f"{cert['lhs']} {cert['rhs']}", spec)
        if reserved:
            return self._inconclusive(_reserved_message(reserved))

        symbols = self._symbols(sp, spec or {})
        try:
            lhs = sp.sympify(cert["lhs"], locals=symbols)
            rhs = sp.sympify(cert["rhs"], locals=symbols)
        except (sp.SympifyError, SyntaxError, TypeError) as exc:
            return self._inconclusive(f"could not parse lhs/rhs: {exc}")

        try:
            diff = sp.simplify(lhs - rhs)
        except (TypeError, ValueError) as exc:
            return self._inconclusive(f"could not simplify lhs - rhs: {exc}")

        # Does accepting this say anything general? A certificate whose two sides are
        # closed arithmetic checks one instance, however true it is.
        general = bool(getattr(lhs, "free_symbols", set()) | getattr(rhs, "free_symbols", set()))
        result = self._decide(sp, relation, diff)
        result.general = general
        return result

    def _symbols(self, sp, vars_spec) -> dict:  # noqa: ANN001
        out: dict = {}
        if isinstance(vars_spec, (list, tuple, set)):
            # A bare list of names means "plain symbols, no assumptions".
            vars_spec = {str(n): "" for n in vars_spec}
        if not isinstance(vars_spec, dict):
            return out
        for name, kind in vars_spec.items():
            assumptions = {}
            k = str(kind).lower()
            if k in ("real", "complex", "integer", "positive", "negative", "nonnegative"):
                assumptions[k if k != "nonnegative" else "nonnegative"] = True
            out[name] = sp.Symbol(name, **assumptions)
        return out

    def _decide(self, sp, relation: str, diff) -> VerificationResult:  # noqa: ANN001
        """Map (relation, simplified lhs-rhs) onto an honest verdict."""
        # A sympy Matrix never equals the integer 0, so ``diff == 0`` is False even when
        # every entry is zero. That turned a *correct* matrix identity into "the identity
        # does not hold" — observed on the Hadamard dossier, where H·Hᵀ = 4I was rejected
        # twice with the zero matrix printed in the rejection itself. Telling a model its
        # correct proof is wrong is the worst thing this backend can do, and the run shows
        # the cost: it abandoned the real identity and submitted "1+1 = 2" instead.
        is_matrix = isinstance(diff, sp.MatrixBase)
        if is_matrix:
            is_zero = bool(getattr(sp.simplify(diff), "is_zero_matrix", False))
        else:
            is_zero = diff == 0 or sp.simplify(diff) == 0
        if relation == "eq":
            if is_zero:
                return self._accepted(
                    "lhs - rhs simplifies to the zero matrix (identity)."
                    if is_matrix
                    else "lhs - rhs simplifies to 0 (identity)."
                )
            return self._rejected(f"lhs - rhs = {diff} != 0; the identity does not hold.")
        if relation == "ne":
            if is_zero:
                return self._rejected("lhs - rhs simplifies to 0, contradicting lhs != rhs.")
            return self._inconclusive("inequation of expressions is not settled symbolically.")
        if is_matrix:
            # "<=" between matrices has no single meaning (entrywise? Loewner order?), so
            # deciding one silently would be a guess about what was asked.
            return self._inconclusive(
                "an order relation between matrices is ambiguous here (entrywise? "
                "positive-semidefinite order?). Compare a scalar instead — a norm, a "
                "determinant, an eigenvalue, or a single entry — or submit the "
                "entrywise statements separately."
            )
        # Order relations need a provably constant sign of the difference. A genuine
        # inequality in free variables ("for all x1, x2: …") is not decided by
        # simplification, and saying only that leaves the model stuck with a correct
        # statement and no route — observed live on a power-mean inequality. Name the
        # routes that do exist for this shape.
        if not getattr(diff, "is_number", False):
            free = sorted(str(s) for s in getattr(diff, "free_symbols", set()))
            names = ", ".join(free[:6]) or "the free variables"
            return self._inconclusive(
                f"order relation needs a constant-sign difference; lhs - rhs = {diff} "
                f"still depends on {names}. This backend decides identities and "
                "constant comparisons, not universally quantified inequalities. Routes "
                "that do work: (a) prove it on a bounded box with "
                "proof_submit(backend='interval') — rigorous, but only for that box; "
                "(b) reduce it to an identity (e.g. show the difference equals an "
                "explicitly non-negative expression, then submit THAT as relation='eq'); "
                "(c) for quantifier-free arithmetic over the reals, submit the negation "
                "to proof_submit(backend='smt') and get 'unsat'; (d) if none apply, "
                "record it as a [GAP-n] rather than as verified."
            )
        try:
            ok = {
                "le": diff <= 0,
                "lt": diff < 0,
                "ge": diff >= 0,
                "gt": diff > 0,
            }[relation]
        except TypeError:
            return self._inconclusive(f"could not compare the difference {diff} to 0.")
        if bool(ok):
            return self._accepted(f"lhs - rhs = {diff} satisfies the '{relation}' relation.")
        return self._rejected(f"lhs - rhs = {diff} violates the '{relation}' relation.")

    def _accepted(self, msg: str) -> VerificationResult:
        return VerificationResult(
            backend=self.name, backend_version=self.version(), accepted=True, output=msg
        )

    def _rejected(self, msg: str) -> VerificationResult:
        return VerificationResult(
            backend=self.name, backend_version=self.version(), accepted=False, output=msg
        )

    def _inconclusive(self, msg: str) -> VerificationResult:
        return VerificationResult(
            backend=self.name,
            backend_version=self.version(),
            accepted=False,
            inconclusive=True,
            output=msg,
        )
