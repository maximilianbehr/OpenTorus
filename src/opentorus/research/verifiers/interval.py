"""Validated-numerics verifier via interval arithmetic (rigorous enclosures).

Unlike a floating-point experiment, interval arithmetic is *sound*: the true value
of an expression over a box of inputs is guaranteed to lie inside the computed
enclosure. This backend therefore produces a real verification artifact — it can
certify, for example, that ``f(x) < 0`` holds for every ``x`` in a box (refuting an
inequality), which is enough to confirm a counterexample candidate.

A certificate is a small JSON object::

    {
      "variables": {"x": [1.0, 2.0], "y": [0.0, 0.5]},   # interval boxes
      "expression": "x*x - 2*y",                          # safe arithmetic only
      "relation": "<",                                    # <, <=, >, >=
      "bound": 0.0,
      "precision": 50                                      # mpmath decimal digits
    }

``accepted`` is True only when the *entire* enclosure satisfies the relation against
the bound — i.e. the relation provably holds for all points in the box. A straddling
enclosure yields ``accepted=False`` (inconclusive; refine the box or precision),
reported honestly, never as a proof. Expressions are evaluated with a restricted AST
walker (no ``eval``) over a whitelist of operators and functions.
"""

from __future__ import annotations

import ast
import json

from opentorus.research.verifiers.base import VerificationResult

_ALLOWED_FUNCS = {"sqrt", "exp", "log", "sin", "cos", "tan", "abs"}
_RELATIONS = {"<", "<=", ">", ">="}


_BOX_ALIASES = ("variables", "domain", "box", "boxes", "bounds", "intervals", "vars")


def _variable_boxes(cert: dict) -> dict | None:
    """Read the variable boxes out of a certificate, tolerating the usual shapes.

    Models split this in ways the documented form does not cover — most often the
    names in ``variables`` and the boxes in a separate ``domain`` map::

        {"variables": ["x"], "domain": {"x": [1, 2]}}

    Observed live: a model submitted exactly that twice in a row, *after* being
    shown a valid example, because its own layout is perfectly reasonable. So we
    merge instead of rejecting: any alias that maps name -> [lo, hi] contributes,
    and a bare list of names is satisfied from the other aliases. Returns ``None``
    only when no boxes can be resolved at all — that stays an honest rejection.
    """
    boxes: dict = {}
    names: list[str] = []
    for key in _BOX_ALIASES:
        value = cert.get(key)
        if isinstance(value, dict):
            for name, box in value.items():
                if isinstance(box, (list, tuple)) and len(box) == 2:
                    boxes.setdefault(str(name), list(box))
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    names.append(item)
                # [["x", 1, 2], ...] and [["x", [1, 2]], ...]
                elif isinstance(item, (list, tuple)) and len(item) in (2, 3):
                    name = str(item[0])
                    rest = item[1] if len(item) == 2 else item[1:]
                    if isinstance(rest, (list, tuple)) and len(rest) == 2:
                        boxes.setdefault(name, list(rest))
    if not boxes:
        return None
    if names and not all(n in boxes for n in names):
        return None  # names given but no boxes for them — say so rather than guess
    return boxes


class IntervalVerifier:
    """Rigorous validated-numerics backend exposed through the verifier protocol."""

    name = "interval"

    def is_available(self) -> bool:
        try:
            import mpmath  # noqa: F401
        except ImportError:
            return False
        return True

    def version(self) -> str | None:
        try:
            import mpmath
        except ImportError:
            return None
        return getattr(mpmath, "__version__", None)

    def verify(self, source: str) -> VerificationResult:
        if not self.is_available():
            return VerificationResult(
                backend=self.name,
                accepted=False,
                available=False,
                output="mpmath is not installed; validated-numerics verification unavailable.",
            )
        try:
            cert = json.loads(source)
        except json.JSONDecodeError as exc:
            return self._invalid(f"certificate is not valid JSON: {exc}")
        return self._verify_certificate(cert)

    # -- internals ---------------------------------------------------------------

    def _invalid(self, message: str) -> VerificationResult:
        return VerificationResult(
            backend=self.name,
            accepted=False,
            # A certificate this backend cannot read was never checked. Marking it
            # rejected would tell the model its mathematics is wrong when the real
            # problem is the JSON shape (the sympy backend already reports it this
            # way; the two backends must not disagree about what a bad input means).
            inconclusive=True,
            available=True,
            output=f"invalid certificate: {message}",
        )

    def _verify_certificate(self, cert: dict) -> VerificationResult:
        import mpmath

        relation = cert.get("relation")
        if relation not in _RELATIONS:
            return self._invalid(f"relation must be one of {sorted(_RELATIONS)}, got {relation!r}")
        expression = cert.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            return self._invalid("'expression' must be a non-empty string")
        variables = _variable_boxes(cert)
        if variables is None:
            return self._invalid(
                "could not read the variable boxes: give them as an object of "
                "name -> [lo, hi] under 'variables' (or list the names in "
                "'variables' and their boxes in 'domain'/'box'/'bounds')"
            )
        try:
            bound = float(cert.get("bound", 0.0))
        except (TypeError, ValueError):
            return self._invalid("'bound' must be a number")
        precision = int(cert.get("precision", 50))

        iv = mpmath.iv
        iv.dps = max(15, precision)
        try:
            env = {}
            for name, box in variables.items():
                if not (isinstance(box, list | tuple) and len(box) == 2):
                    return self._invalid(f"variable '{name}' must be a [lo, hi] pair")
                lo, hi = box
                env[name] = iv.mpf([mpmath.mpf(str(lo)), mpmath.mpf(str(hi))])
            tree = ast.parse(expression, mode="eval")
            enclosure = _eval_interval(tree.body, env, iv)
        except _UnsafeExpression as exc:
            return self._invalid(f"unsupported expression: {exc}")
        except Exception as exc:  # noqa: BLE001 — arithmetic/domain errors are honest failures
            return self._invalid(f"evaluation failed: {exc}")

        lo = float(enclosure.a)
        hi = float(enclosure.b)
        b = mpmath.mpf(str(bound))
        if relation == "<":
            accepted = enclosure.b < b
        elif relation == "<=":
            accepted = enclosure.b <= b
        elif relation == ">":
            accepted = enclosure.a > b
        else:  # ">="
            accepted = enclosure.a >= b

        verdict = "PROVED" if accepted else "INCONCLUSIVE"
        output = (
            f"enclosure of '{expression}' over the box = [{lo:.6g}, {hi:.6g}]; "
            f"relation '{expression} {relation} {bound}': {verdict} "
            f"(rigorous interval arithmetic, dps={iv.dps})."
        )
        if not accepted:
            output += " The enclosure straddles the bound — refine the box or raise precision."
        return VerificationResult(
            backend=self.name,
            backend_version=self.version(),
            accepted=bool(accepted),
            # Interval arithmetic is one-sided: an enclosure that straddles the bound
            # fails to *prove* the inequality but does not *disprove* it — the box may
            # simply be too coarse. Reporting that as REJECTED told the model a true
            # inequality was false. (The output text already said "refine the box".)
            inconclusive=not accepted,
            available=True,
            output=output,
            outcome=verdict.lower(),
        )


class _UnsafeExpression(Exception):
    """Raised when an expression contains a node outside the safe whitelist."""


def _eval_interval(node: ast.AST, env: dict, iv):  # noqa: ANN001
    """Evaluate an AST node over interval arithmetic, allowing only a safe subset."""
    if isinstance(node, ast.BinOp):
        left = _eval_interval(node.left, env, iv)
        right = _eval_interval(node.right, env, iv)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        raise _UnsafeExpression(f"operator {type(node.op).__name__}")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_interval(node.operand, env, iv)
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise _UnsafeExpression(f"unary {type(node.op).__name__}")
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _UnsafeExpression(f"constant {node.value!r}")
        import mpmath

        return iv.mpf(mpmath.mpf(str(node.value)))
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id == "pi":
            return iv.pi
        if node.id == "e":
            return iv.e
        raise _UnsafeExpression(f"unknown name '{node.id}'")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise _UnsafeExpression("only sqrt/exp/log/sin/cos/tan/abs calls are allowed")
        if len(node.args) != 1 or node.keywords:
            raise _UnsafeExpression("functions take exactly one positional argument")
        arg = _eval_interval(node.args[0], env, iv)
        if node.func.id == "abs":
            return abs(arg)
        return getattr(iv, node.func.id)(arg)
    raise _UnsafeExpression(type(node).__name__)
