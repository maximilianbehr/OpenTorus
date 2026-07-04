"""Convention check on the known case: inverse graph Laplacians.

The problem statement cites the inverse-Laplacian case (K = (L + gamma I)^{-1},
gamma -> 0+) as the setting where the relevant property holds and yields the
e^{-k/s} greedy bound. The word "submodular" is convention-dependent for a
decreasing error function, so this script tests BOTH readings on random
connected graph Laplacians (gamma = 1/1000, exact rationals):

  literal:      f(S u {i}) - f(S) >= f(T u {i}) - f(T)   ("f is submodular")
  diminishing:  f(S u {i}) - f(S) <= f(T u {i}) - f(T)   (error-reduction has
                                                          diminishing returns)

Whichever direction holds on the known case is the one the open problem means.
"""

from __future__ import annotations

import random

from sympy import Matrix, Rational


def laplacian(n: int, rng: random.Random) -> Matrix:
    a = [[Rational(0)] * n for _ in range(n)]
    edges = set()
    for i in range(1, n):  # random spanning tree keeps the graph connected
        edges.add((rng.randrange(i), i))
    for _ in range(n):
        i, j = rng.sample(range(n), 2)
        edges.add((min(i, j), max(i, j)))
    for i, j in edges:
        w = Rational(rng.randint(1, 3))
        a[i][j] -= w
        a[j][i] -= w
        a[i][i] += w
        a[j][j] += w
    return Matrix(a)


def nystrom_error(k: Matrix, s: tuple[int, ...]) -> Rational:
    cols = list(s)
    c = k[:, cols]
    w = k[cols, cols]
    return k.trace() - (c * w.inv() * c.T).trace()


def main() -> int:
    rng = random.Random(11)
    n = 6
    literal_viol = diminishing_viol = checks = 0
    for _ in range(8):
        big_l = laplacian(n, rng)
        k = (big_l + Rational(1, 1000) * Matrix.eye(n)).inv()
        for _ in range(6):
            t = tuple(sorted(rng.sample(range(n), rng.randint(2, 4))))
            s = tuple(sorted(rng.sample(t, rng.randint(1, len(t) - 1))))
            i = rng.choice([x for x in range(n) if x not in t])
            m_s = nystrom_error(k, tuple(sorted((*s, i)))) - nystrom_error(k, s)
            m_t = nystrom_error(k, tuple(sorted((*t, i)))) - nystrom_error(k, t)
            checks += 1
            if m_s < m_t:
                literal_viol += 1
            if m_s > m_t:
                diminishing_viol += 1
    print(f"inverse Laplacian (gamma=1/1000, n={n}): {checks} exact checks")
    print(f"  violations of literal 'f submodular' reading: {literal_viol}")
    print(f"  violations of diminishing error-reduction:    {diminishing_viol}")
    print(
        "the diminishing error-reduction reading matches the known case"
        if diminishing_viol == 0 and literal_viol > 0
        else "inconclusive — inspect counts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
