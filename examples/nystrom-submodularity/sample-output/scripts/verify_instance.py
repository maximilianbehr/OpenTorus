"""Independent exact verification of the SDD counterexample candidate.

Pure Python fractions + Gaussian elimination — no sympy, so a sympy bug
cannot produce a false positive. Everything is exact rational arithmetic.
"""
from fractions import Fraction as F

L = [
    [F(8),      F(3,2),  F(-1,4), F(-3,4), F(1),    F(-3,2)],
    [F(3,2),    F(26,3), F(-3,2), F(-1,3), F(4,3),  F(1)],
    [F(-1,4),   F(-3,2), F(9,2),  F(-1),   F(-1,2), F(-1,4)],
    [F(-3,4),   F(-1,3), F(-1),   F(61,12),F(-3,2), F(1,2)],
    [F(1),      F(4,3),  F(-1,2), F(-3,2), F(28,3), F(-2)],
    [F(-3,2),   F(1),    F(-1,4), F(1,2),  F(-2),   F(33,4)],
]
n = 6

# 1. symmetric + strictly diagonally dominant (positive diagonal) => PD
assert all(L[i][j] == L[j][i] for i in range(n) for j in range(n))
for i in range(n):
    assert L[i][i] > sum(abs(L[i][j]) for j in range(n) if j != i), f"row {i} not strictly dominant"
# PD double-check: leading principal minors all positive (exact fraction-LU)
def det(m):
    m = [row[:] for row in m]; k = len(m); d = F(1)
    for c in range(k):
        p = next((r for r in range(c, k) if m[r][c] != 0), None)
        assert p is not None
        if p != c: m[c], m[p] = m[p], m[c]; d = -d
        d *= m[c][c]
        for r in range(c + 1, k):
            f = m[r][c] / m[c][c]
            m[r] = [m[r][j] - f * m[c][j] for j in range(k)]
    return d
for k in range(1, n + 1):
    assert det([row[:k] for row in L[:k]]) > 0
print("L is symmetric, strictly diagonally dominant (SDD), positive-definite: OK")

def inverse(m):
    k = len(m)
    aug = [row[:] + [F(int(i == j)) for j in range(k)] for i, row in enumerate(m)]
    for c in range(k):
        p = next(r for r in range(c, k) if aug[r][c] != 0)
        aug[c], aug[p] = aug[p], aug[c]
        piv = aug[c][c]
        aug[c] = [x / piv for x in aug[c]]
        for r in range(k):
            if r != c and aug[r][c] != 0:
                f = aug[r][c]
                aug[r] = [aug[r][j] - f * aug[c][j] for j in range(2 * k)]
    return [row[k:] for row in aug]

def matmul(a, b):
    return [[sum(a[i][t] * b[t][j] for t in range(len(b))) for j in range(len(b[0]))] for i in range(len(a))]

K = inverse(L)
def err(I):
    cols = list(I)
    C = [[K[r][c] for c in cols] for r in range(n)]          # K[:, I]
    W = [[K[r][c] for c in cols] for r in cols]              # K[I, I]
    Winv = inverse(W)
    N = matmul(matmul(C, Winv), [[C[r][c] for c in range(len(cols))] for r in range(n)] and [list(row) for row in zip(*C)])
    trK = sum(K[i][i] for i in range(n))
    trN = sum(N[i][i] for i in range(n))
    return trK - trN

S, T, i = (0,), (0, 3), 5
mS = err(tuple(sorted((*S, i)))) - err(S)
mT = err(tuple(sorted((*T, i)))) - err(T)
print(f"f(S+i)-f(S) = {mS}")
print(f"f(T+i)-f(T) = {mT}")
print(f"expected     -207777829717/1469109624035 and -156716773/1107431115")
assert mS == F(-207777829717, 1469109624035), "mS mismatch with sympy computation!"
assert mT == F(-156716773, 1107431115), "mT mismatch with sympy computation!"
assert mS > mT
print("CONFIRMED: f(S∪{i}) - f(S) > f(T∪{i}) - f(T)  — diminishing error-reduction fails on this SDD-PD instance (exact arithmetic, two independent implementations).")
