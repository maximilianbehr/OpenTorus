"""Symbolic algebra sanity checks for optimization-style claims.

Machine-written research frequently asserts a clean interior optimum — "the
work-minimizing parameter is m* = …" — for an objective that is in fact monotone,
so the real optimum sits at a boundary. This module catches that class of error
with calculus rather than rhetoric.

Given a scalar objective ``W(m)`` (and, optionally, a claimed optimizer ``m*`` and
a domain), :func:`check_optimizer` differentiates ``W``, solves for the interior
critical points, decides whether ``W`` is monotone on the domain, and verifies
that any claimed ``m*`` actually satisfies ``dW/dm = 0``. It returns a structured,
serializable verdict.

``sympy`` is an optional dependency (the ``algebra`` extra) and is imported lazily
so the base CLI stays importable and fast without it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckVerdict = Literal["consistent", "rejected", "inconclusive", "unavailable"]

# Fixed sample points used to infer the sign of the derivative. Deterministic by
# construction (no randomness), so the verdict is reproducible from inputs alone.
_SAMPLE_POINTS = (-100, -10, -2, -1, 0, 1, 2, 10, 100)


class AlgebraCheckResult(BaseModel):
    """A serializable verdict on an optimization claim."""

    expression: str
    variable: str
    derivative: str = ""
    critical_points: list[str] = Field(default_factory=list)
    is_monotone: bool | None = None
    monotonicity: str = "unknown"
    domain: tuple[str, str] | None = None
    claimed_optimizer: str | None = None
    optimizer_is_critical: bool | None = None
    optimizer_derivative_value: str | None = None
    boundary_candidates: list[str] = Field(default_factory=list)
    verdict: CheckVerdict = "inconclusive"
    detail: str = ""
    warnings: list[str] = Field(default_factory=list)


def sympy_available() -> bool:
    """Return whether the optional ``sympy`` dependency is importable."""
    try:
        import sympy  # noqa: F401
    except ImportError:
        return False
    return True


def check_optimizer(
    expression: str,
    *,
    variable: str = "m",
    claimed_optimizer: str | None = None,
    domain: tuple[str, str] | None = None,
) -> AlgebraCheckResult:
    """Check a claimed interior optimizer ``m*`` of an objective ``W(variable)``.

    Returns a structured result. The verdict is:

    * ``rejected`` — the objective is monotone on the domain (so no interior
      optimum exists), or the claimed ``m*`` does not satisfy ``dW/dm = 0``.
    * ``consistent`` — the claimed ``m*`` is a genuine interior critical point.
    * ``inconclusive`` — symbolic analysis could not settle the question.
    * ``unavailable`` — ``sympy`` is not installed.
    """
    result = AlgebraCheckResult(
        expression=expression,
        variable=variable,
        claimed_optimizer=claimed_optimizer,
        domain=domain,
    )
    if not sympy_available():
        result.verdict = "unavailable"
        result.detail = (
            "sympy is not installed. Install the optional extra: pip install 'opentorus[algebra]'."
        )
        return result

    import sympy as sp

    sym = sp.Symbol(variable, real=True)
    try:
        expr = sp.sympify(expression, locals={variable: sym})
    except (sp.SympifyError, SyntaxError, TypeError) as exc:
        result.verdict = "inconclusive"
        result.detail = f"Could not parse expression '{expression}': {exc}"
        return result

    free = expr.free_symbols
    extra = sorted(str(s) for s in free if s != sym)
    if extra:
        result.warnings.append(
            f"Expression has free symbols besides '{variable}': {', '.join(extra)}. "
            "They are treated as opaque constants; results may be conditional on them."
        )

    deriv = sp.diff(expr, sym)
    result.derivative = str(deriv)

    lo = hi = None
    if domain is not None:
        try:
            lo = sp.sympify(domain[0], locals={variable: sym})
            hi = sp.sympify(domain[1], locals={variable: sym})
        except (sp.SympifyError, SyntaxError, TypeError):
            result.warnings.append(f"Could not parse domain {domain}; ignoring it.")
            lo = hi = None

    # Interior critical points (dW/dm = 0), restricted to the domain when given.
    try:
        roots = sp.solve(sp.Eq(deriv, 0), sym)
    except Exception:  # noqa: BLE001 - the symbolic solver is best-effort
        roots = []
    real_roots = [r for r in roots if getattr(r, "is_real", None) is not False]
    interior_roots = [r for r in real_roots if _strictly_inside(sp, r, lo, hi)]
    result.critical_points = [str(r) for r in real_roots]

    # Monotonicity: sample the derivative's sign at fixed points inside the domain.
    is_monotone, direction = _infer_monotonicity(sp, deriv, sym, lo, hi, interior_roots)
    result.is_monotone = is_monotone
    result.monotonicity = direction

    if is_monotone and lo is not None and hi is not None:
        # A monotone objective attains its optimum at a boundary, never inside.
        result.boundary_candidates = [str(lo), str(hi)]

    # Validate any claimed optimizer against the calculus.
    if claimed_optimizer is not None:
        _evaluate_claimed_optimizer(sp, result, deriv, sym, claimed_optimizer, lo, hi, is_monotone)
    else:
        if is_monotone:
            result.verdict = "rejected"
            result.detail = (
                f"W({variable}) is monotone ({direction}); it has no interior optimum. "
                "Any claimed interior optimizer is false — the optimum is at a boundary."
            )
        elif interior_roots:
            result.verdict = "consistent"
            result.detail = (
                f"W({variable}) has interior critical point(s): "
                f"{', '.join(str(r) for r in interior_roots)}."
            )
        else:
            result.verdict = "inconclusive"
            result.detail = "No claimed optimizer given and monotonicity is undetermined."
    return result


def _strictly_inside(sp, value, lo, hi) -> bool:  # noqa: ANN001
    """True if ``value`` is a finite real strictly inside (lo, hi); unbounded if no domain."""
    if not getattr(value, "is_number", False):
        return True  # symbolic root: cannot exclude it from the domain
    if lo is None or hi is None:
        return True
    try:
        return bool(sp.simplify(value - lo) > 0) and bool(sp.simplify(hi - value) > 0)
    except TypeError:
        return False


def _infer_monotonicity(sp, deriv, sym, lo, hi, interior_roots):  # noqa: ANN001, ANN202
    """Infer monotonicity from the sign of the derivative at fixed sample points.

    A sign change, or an interior stationary point, means *not* monotone. A single
    constant sign with no interior root means monotone (increasing/decreasing).
    """
    if interior_roots:
        return False, "not monotone (has interior critical point)"

    signs: set[int] = set()
    sampled = 0
    for p in _SAMPLE_POINTS:
        pv = sp.Integer(p)
        if lo is not None and hi is not None:
            try:
                if not (bool(sp.simplify(pv - lo) >= 0) and bool(sp.simplify(hi - pv) >= 0)):
                    continue
            except TypeError:
                continue
        try:
            val = sp.simplify(deriv.subs(sym, pv))
        except (TypeError, ValueError):
            continue
        if not getattr(val, "is_number", False):
            return None, "unknown (derivative has free constants)"
        try:
            if val > 0:
                signs.add(1)
            elif val < 0:
                signs.add(-1)
            else:
                signs.add(0)
        except TypeError:
            return None, "unknown"
        sampled += 1

    if sampled == 0:
        return None, "unknown (no sample points in domain)"
    nonzero = {s for s in signs if s != 0}
    if len(nonzero) > 1:
        return False, "not monotone (derivative changes sign)"
    if nonzero == {1}:
        return True, "strictly increasing"
    if nonzero == {-1}:
        return True, "strictly decreasing"
    return None, "unknown"


def _evaluate_claimed_optimizer(  # noqa: ANN001
    sp, result, deriv, sym, claimed_optimizer, lo, hi, is_monotone
) -> None:
    """Fill the verdict for a claimed optimizer m* against dW/dm and monotonicity."""
    try:
        m_star = sp.sympify(claimed_optimizer, locals={str(sym): sym})
    except (sp.SympifyError, SyntaxError, TypeError) as exc:
        result.verdict = "inconclusive"
        result.detail = f"Could not parse claimed optimizer '{claimed_optimizer}': {exc}"
        return

    try:
        dval = sp.simplify(deriv.subs(sym, m_star))
    except (TypeError, ValueError) as exc:
        result.verdict = "inconclusive"
        result.detail = f"Could not evaluate dW/d{sym} at {claimed_optimizer}: {exc}"
        return
    result.optimizer_derivative_value = str(dval)

    is_critical: bool | None
    try:
        is_critical = bool(dval == 0) or bool(sp.simplify(dval) == 0)
    except TypeError:
        is_critical = None
    result.optimizer_is_critical = is_critical

    interior = _strictly_inside(sp, m_star, lo, hi)

    if is_monotone and interior:
        result.verdict = "rejected"
        result.detail = (
            f"W({sym}) is monotone ({result.monotonicity}); it has no interior optimum, so "
            f"the claimed interior optimizer {sym}* = {claimed_optimizer} is false. The "
            "optimum lies at a domain boundary."
        )
        return
    if is_critical is False:
        result.verdict = "rejected"
        result.detail = (
            f"The claimed optimizer {sym}* = {claimed_optimizer} does NOT satisfy "
            f"dW/d{sym} = 0 (it evaluates to {dval}); it is not a stationary point."
        )
        return
    if is_critical:
        result.verdict = "consistent"
        result.detail = (
            f"The claimed optimizer {sym}* = {claimed_optimizer} satisfies dW/d{sym} = 0; "
            "it is a genuine stationary point (check the second-order condition for a "
            "minimum vs maximum)."
        )
        return
    result.verdict = "inconclusive"
    result.detail = (
        f"Could not symbolically decide whether dW/d{sym} vanishes at {claimed_optimizer} "
        f"(value: {dval})."
    )
