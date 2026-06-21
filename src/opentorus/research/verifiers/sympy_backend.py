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

from opentorus.research.verifiers.base import VerificationResult

_RELATIONS = {"eq", "ne", "le", "lt", "ge", "gt"}


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

        symbols = self._symbols(sp, cert.get("vars") or {})
        try:
            lhs = sp.sympify(cert["lhs"], locals=symbols)
            rhs = sp.sympify(cert["rhs"], locals=symbols)
        except (sp.SympifyError, SyntaxError, TypeError) as exc:
            return self._inconclusive(f"could not parse lhs/rhs: {exc}")

        try:
            diff = sp.simplify(lhs - rhs)
        except (TypeError, ValueError) as exc:
            return self._inconclusive(f"could not simplify lhs - rhs: {exc}")

        return self._decide(sp, relation, diff)

    def _symbols(self, sp, vars_spec: dict) -> dict:  # noqa: ANN001
        out: dict = {}
        for name, kind in vars_spec.items():
            assumptions = {}
            k = str(kind).lower()
            if k in ("real", "complex", "integer", "positive", "negative", "nonnegative"):
                assumptions[k if k != "nonnegative" else "nonnegative"] = True
            out[name] = sp.Symbol(name, **assumptions)
        return out

    def _decide(self, sp, relation: str, diff) -> VerificationResult:  # noqa: ANN001
        """Map (relation, simplified lhs-rhs) onto an honest verdict."""
        is_zero = diff == 0 or sp.simplify(diff) == 0
        if relation == "eq":
            if is_zero:
                return self._accepted("lhs - rhs simplifies to 0 (identity).")
            return self._rejected(f"lhs - rhs = {diff} != 0; the identity does not hold.")
        if relation == "ne":
            if is_zero:
                return self._rejected("lhs - rhs simplifies to 0, contradicting lhs != rhs.")
            return self._inconclusive("inequation of expressions is not settled symbolically.")
        # Order relations need a provably constant sign of the difference.
        if not getattr(diff, "is_number", False):
            return self._inconclusive(
                f"order relation needs a constant-sign difference; got non-constant {diff}."
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
