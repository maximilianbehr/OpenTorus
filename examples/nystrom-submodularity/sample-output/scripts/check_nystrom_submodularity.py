"""Exact-arithmetic diminishing-returns sweep for the nuclear Nystrom error.

Let L be symmetric positive-definite, K = L^{-1} (the gamma -> 0+ limit of
(L + gamma I)^{-1} for positive-definite L), and for a non-empty index set I

    f(I) = ||K - K[:,I] K[I,I]^{-1} K[I,:]||_* = tr(K) - tr(K[:,I] K[I,I]^{-1} K[I,:])

(the residual is positive semidefinite, so its nuclear norm is its trace).
This sweep samples random SDDM (--cls sddm: non-positive off-diagonals) or
generic SDD (--cls sdd: mixed-sign off-diagonals) strictly diagonally dominant
matrices with rational entries and tests, in exact rational arithmetic, the
diminishing error-reduction inequality on random nested pairs:

    f(S u {i}) - f(S) <= f(T u {i}) - f(T)   for non-empty S subset of T, i not in T.

Evidence only: a clean sweep supports the property on the sampled instances;
it does not verify the general statement. A strict violation, being exact, is
a counterexample candidate for the sampled setting.
"""

from __future__ import annotations

import argparse
import random
from fractions import Fraction

from sympy import Matrix, Rational


def random_sdd(n: int, rng: random.Random, cls: str) -> Matrix:
    a = [[Rational(0)] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            v = Fraction(rng.randint(1, 4), rng.randint(1, 4))
            if cls == "sddm":
                v = -v  # SDDM: non-positive off-diagonals
            elif rng.random() < 0.5:
                v = -v  # generic SDD: mixed signs
            a[i][j] = Rational(v)
            a[j][i] = Rational(v)
    for i in range(n):
        off = sum(abs(a[i][j]) for j in range(n) if j != i)
        a[i][i] = off + Rational(rng.randint(1, 3))  # strict dominance -> positive-definite
    return Matrix(a)


def nystrom_error(k: Matrix, s: tuple[int, ...]) -> Rational:
    cols = list(s)
    c = k[:, cols]
    w = k[cols, cols]
    return k.trace() - (c * w.inv() * c.T).trace()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cls", choices=("sddm", "sdd"), required=True)
    parser.add_argument("--n", type=int, default=6)
    parser.add_argument("--trials", type=int, default=15)
    parser.add_argument("--pairs", type=int, default=6, help="nested subset pairs per matrix")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    checks = 0
    violations = 0
    for trial in range(args.trials):
        big_l = random_sdd(args.n, rng, args.cls)
        k = big_l.inv()
        for _ in range(args.pairs):
            t = tuple(sorted(rng.sample(range(args.n), rng.randint(2, args.n - 2))))
            s = tuple(sorted(rng.sample(t, rng.randint(1, len(t) - 1))))
            i = rng.choice([x for x in range(args.n) if x not in t])
            m_s = nystrom_error(k, tuple(sorted((*s, i)))) - nystrom_error(k, s)
            m_t = nystrom_error(k, tuple(sorted((*t, i)))) - nystrom_error(k, t)
            checks += 1
            if m_s > m_t:  # exact rationals: any strict violation is real for this instance
                violations += 1
                print(f"VIOLATION trial={trial} S={s} T={t} i={i}")
                print(f"  f(S+i)-f(S) = {m_s}")
                print(f"  f(T+i)-f(T) = {m_t}")
                print("  L rows:")
                for r in range(big_l.rows):
                    print("   ", [str(big_l[r, c]) for c in range(big_l.cols)])
    print(
        f"{args.cls}: checked {checks} nested-pair inequalities on "
        f"{args.trials} random matrices (n={args.n}, seed={args.seed})"
    )
    print(f"strict violations of diminishing error-reduction: {violations}")
    print(
        "supports the property on these instances (no violation found)"
        if violations == 0
        else "counterexample candidate(s) found — see instances above"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
