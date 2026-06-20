"""Math-aware computational experiments (Milestone 50).

Conjectures are investigated *computationally*: symbolic checks and bounded
counterexample searches. The cardinal rule is honesty about scope — "no
counterexample up to N" is recorded as **bounded numerical evidence**, never as
"true". A found counterexample is strong contradicting evidence (a refutation).

The search helpers are pure and stdlib-only, so they run and test without SymPy
or NumPy; the experiment *templates* may use those optional libraries.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

MathTemplate = Literal["symbolic", "numerical", "counterexample_search", "validated_numerics"]


class CounterexampleResult(BaseModel):
    """The outcome of a bounded counterexample search over a stated domain."""

    predicate: str = ""
    start: int
    stop: int
    step: int = 1
    checked: int = 0
    found: bool = False
    counterexample: int | None = None

    def evidence_summary(self) -> str:
        domain = f"[{self.start}, {self.stop}] step {self.step}"
        if self.found:
            return (
                f"Counterexample found at n={self.counterexample} within {domain}: "
                f"this refutes the conjecture '{self.predicate or 'P(n)'}'."
            )
        return (
            f"No counterexample to '{self.predicate or 'P(n)'}' in {domain} "
            f"({self.checked} value(s) checked). Bounded numerical evidence only — "
            "this is not a proof."
        )


def counterexample_search(
    predicate: Callable[[int], bool],
    start: int,
    stop: int,
    step: int = 1,
    *,
    description: str = "",
) -> CounterexampleResult:
    """Search ``[start, stop]`` for an ``n`` where ``predicate(n)`` is False.

    ``predicate(n)`` should return True when the conjecture *holds* for ``n``; the
    first ``n`` for which it returns False is a counterexample. The searched range
    is always recorded so the result reads as bounded evidence.
    """
    if step <= 0:
        raise ValueError("step must be a positive integer.")
    checked = 0
    n = start
    while n <= stop:
        checked += 1
        if not predicate(n):
            return CounterexampleResult(
                predicate=description,
                start=start,
                stop=stop,
                step=step,
                checked=checked,
                found=True,
                counterexample=n,
            )
        n += step
    return CounterexampleResult(
        predicate=description,
        start=start,
        stop=stop,
        step=step,
        checked=checked,
        found=False,
        counterexample=None,
    )


class VerifiedBounds(BaseModel):
    """A *rigorous* numerical enclosure over a stated (continuous) domain.

    Distinct from M50 sampling: an interval/validated-numerics computation that
    encloses the quantity over the entire domain. ``excludes_counterexample`` is
    True when the enclosure rigorously rules out a counterexample (e.g. the
    enclosure stays strictly positive), turning "no counterexample sampled" into
    a machine-checkable bound.
    """

    quantity: str = ""
    domain: str = ""
    lower: float
    upper: float
    rounding: str = "outward"
    method: str = "interval_arithmetic"
    library: str | None = None
    rigorous: bool = True
    excludes_counterexample: bool = False
    note: str = ""

    def bound_summary(self) -> str:
        head = (
            f"Rigorous enclosure of {self.quantity or 'the quantity'} over "
            f"{self.domain or 'the domain'}: [{self.lower}, {self.upper}] "
            f"({self.rounding} rounding via {self.library or self.method})."
        )
        if self.excludes_counterexample:
            return head + " This rigorously excludes a counterexample over the entire domain."
        return head + " A rigorous bound (not sampling), valid over the whole domain."


class SampledEstimate(BaseModel):
    """A degraded, sampled estimate over a finite grid — evidence, not a bound."""

    quantity: str = ""
    domain: str = ""
    samples: int = 0
    min_value: float | None = None
    max_value: float | None = None
    rigorous: bool = False
    note: str = ""

    def evidence_summary(self) -> str:
        rng = ""
        if self.min_value is not None and self.max_value is not None:
            rng = f" in [{self.min_value}, {self.max_value}]"
        return (
            f"Sampled estimate of {self.quantity or 'the quantity'} over "
            f"{self.domain or 'the domain'}{rng} from {self.samples} grid point(s). "
            "Sampling is evidence, not a rigorous bound."
        )


def rigorous_numerics_available() -> bool:
    """Whether an interval-arithmetic library (``mpmath.iv``) is importable."""
    try:
        import mpmath  # noqa: F401
    except ImportError:
        return False
    return True


def parse_numeric_result(stdout: str) -> VerifiedBounds | SampledEstimate | None:
    """Parse a validated-numerics experiment's JSON output.

    Returns a :class:`VerifiedBounds` only when the experiment declares a
    rigorous enclosure (``kind == "verified_bounds"`` and ``rigorous``); a
    sampled fallback is returned as :class:`SampledEstimate`; anything else is
    ``None``.
    """
    payload: dict | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
    if not payload:
        return None
    kind = payload.get("kind")
    if kind == "verified_bounds" and payload.get("rigorous") and "lower" in payload:
        return VerifiedBounds(
            quantity=payload.get("quantity", ""),
            domain=payload.get("domain", ""),
            lower=float(payload["lower"]),
            upper=float(payload["upper"]),
            rounding=payload.get("rounding", "outward"),
            method=payload.get("method", "interval_arithmetic"),
            library=payload.get("library"),
            rigorous=True,
            excludes_counterexample=bool(payload.get("excludes_counterexample", False)),
            note=payload.get("note", ""),
        )
    if kind in ("numerical_sampling", "sampled_estimate"):
        return SampledEstimate(
            quantity=payload.get("quantity", ""),
            domain=payload.get("domain", ""),
            samples=int(payload.get("samples", 0)),
            min_value=payload.get("min_value"),
            max_value=payload.get("max_value"),
            note=payload.get("note", ""),
        )
    return None


def record_bounds_evidence(ot_dir: Path, claim_id: str, result: VerifiedBounds | SampledEstimate):
    """Record a validated-numerics result as evidence, labelled by rigor.

    A rigorous enclosure that excludes a counterexample is *strong* supporting
    evidence over the whole domain; a non-excluding rigorous bound is *moderate*;
    a sampled fallback is *weak* and explicitly not a bound.
    """
    from opentorus.research.evidence import add_evidence

    if isinstance(result, VerifiedBounds):
        strength = "strong" if result.excludes_counterexample else "moderate"
        limitations = (
            [] if result.excludes_counterexample else ["bound holds over the stated domain only"]
        )
        summary = result.bound_summary()
    else:
        strength = "weak"
        limitations = ["sampled grid only", "not a rigorous bound"]
        summary = result.evidence_summary()
    return add_evidence(
        ot_dir,
        claim_id,
        source_type="experiment",
        summary=summary,
        direction="supports",
        strength=strength,
        limitations=limitations,
    )


def record_search_evidence(ot_dir: Path, claim_id: str, result: CounterexampleResult):
    """Link a counterexample search to a claim as evidence (never as proof).

    A found counterexample is strong *contradicting* evidence; a clean bounded
    search is *weak supporting* evidence (bounded, explicitly not a proof).
    """
    from opentorus.research.evidence import add_evidence

    if result.found:
        direction, strength = "contradicts", "strong"
    else:
        direction, strength = "supports", "weak"
    return add_evidence(
        ot_dir,
        claim_id,
        source_type="experiment",
        summary=result.evidence_summary(),
        direction=direction,
        strength=strength,
        limitations=[] if result.found else ["bounded search only", "not a proof"],
    )


_SYMBOLIC_TEMPLATE = '''\
"""Symbolic check experiment (Milestone 50).

Verifies an identity/inequality over a finite range and prints a JSON result.
Uses SymPy when available, else a stdlib fallback. Deterministic (no randomness).
"""

import json

SEED = 0  # deterministic; recorded in the manifest


def holds(n: int) -> bool:
    # Example: the identity sum_{k=1..n} k == n*(n+1)//2. Replace with your claim.
    return sum(range(1, n + 1)) == n * (n + 1) // 2


def main() -> None:
    start, stop = 1, 1000
    all_hold = all(holds(n) for n in range(start, stop + 1))
    print(json.dumps({
        "seed": SEED,
        "kind": "symbolic_check",
        "range": [start, stop],
        "all_hold": all_hold,
        "note": "Checked over a finite range; evidence, not a proof.",
    }))


if __name__ == "__main__":
    main()
'''

_NUMERICAL_TEMPLATE = '''\
"""Numerical experiment (Milestone 50).

Deterministic numerical probe with a fixed seed. Prefer mpmath/NumPy for serious
work; this stdlib template just demonstrates the JSON-result contract.
"""

import json
import random

SEED = 42


def main() -> None:
    random.seed(SEED)
    samples = [random.random() for _ in range(1000)]
    mean = sum(samples) / len(samples)
    print(json.dumps({
        "seed": SEED,
        "kind": "numerical",
        "n": len(samples),
        "mean": round(mean, 6),
        "note": "Single deterministic run; evidence, not validation.",
    }))


if __name__ == "__main__":
    main()
'''

_COUNTEREXAMPLE_TEMPLATE = '''\
"""Counterexample search (Milestone 50).

Searches a STATED domain for a counterexample to a conjecture. Records the exact
range so "no counterexample up to N" is stored as bounded evidence, not "true".
"""

import json

SEED = 0
START, STOP, STEP = 1, 10000, 1


def conjecture_holds(n: int) -> bool:
    # Return True if the conjecture holds for n. Replace with your predicate.
    # Example (true): n*n >= n for non-negative integers.
    return n * n >= n


def main() -> None:
    checked = 0
    counterexample = None
    n = START
    while n <= STOP:
        checked += 1
        if not conjecture_holds(n):
            counterexample = n
            break
        n += STEP
    print(json.dumps({
        "seed": SEED,
        "kind": "counterexample_search",
        "searched_range": [START, STOP],
        "step": STEP,
        "checked": checked,
        "counterexample": counterexample,
        "result": (
            f"counterexample at n={counterexample}"
            if counterexample is not None
            else f"no counterexample up to {STOP} (bounded evidence, not a proof)"
        ),
    }))


if __name__ == "__main__":
    main()
'''

_VALIDATED_NUMERICS_TEMPLATE = '''\
"""Validated (interval) numerics experiment (Milestone 61).

Computes a RIGOROUS enclosure of a quantity over a stated continuous domain
using mpmath's interval arithmetic when available. Outward (directed) rounding
makes the enclosure machine-checkable. Without mpmath the experiment degrades
HONESTLY to a sampled grid estimate and labels it as evidence, not a bound.
"""

import json

QUANTITY = "f(x) = x**2 - x + 1"
DOMAIN = (0.0, 1.0)
ROUNDING = "outward"


def f(x):
    # A rational expression: exact under interval arithmetic. Replace with yours.
    return x * x - x + 1


def main() -> None:
    a, b = DOMAIN
    try:
        from mpmath import iv
    except ImportError:
        iv = None

    if iv is not None:
        iv.dps = 30
        enclosure = f(iv.mpf([a, b]))
        lower, upper = float(enclosure.a), float(enclosure.b)
        print(json.dumps({
            "kind": "verified_bounds",
            "rigorous": True,
            "library": "mpmath.iv",
            "method": "interval_arithmetic",
            "quantity": QUANTITY,
            "domain": f"[{a}, {b}]",
            "rounding": ROUNDING,
            "lower": lower,
            "upper": upper,
            # f stays strictly positive on [0, 1], so it has no real root there.
            "excludes_counterexample": lower > 0,
            "note": "Outward-rounded interval enclosure over the entire domain.",
        }))
    else:
        n = 1001
        values = [f(a + (b - a) * i / (n - 1)) for i in range(n)]
        print(json.dumps({
            "kind": "numerical_sampling",
            "rigorous": False,
            "quantity": QUANTITY,
            "domain": f"[{a}, {b}]",
            "samples": n,
            "min_value": min(values),
            "max_value": max(values),
            "note": "mpmath not installed: sampled grid only - evidence, not a rigorous bound.",
        }))


if __name__ == "__main__":
    main()
'''

MATH_TEMPLATES: dict[str, str] = {
    "symbolic": _SYMBOLIC_TEMPLATE,
    "numerical": _NUMERICAL_TEMPLATE,
    "counterexample_search": _COUNTEREXAMPLE_TEMPLATE,
    "validated_numerics": _VALIDATED_NUMERICS_TEMPLATE,
}
