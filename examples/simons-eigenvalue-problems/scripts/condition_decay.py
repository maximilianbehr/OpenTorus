import numpy as np, json, sys

def hermitian_decay_matrix(n, p):
    # Create diagonal matrix with eigenvalues i^{-p} for i=1..n
    vals = np.array([ (i+1) ** (-p) for i in range(n) ], dtype=float)
    return np.diag(vals)

def krylov_basis(A, b, m):
    n = A.shape[0]
    K = np.zeros((n, m), dtype=A.dtype)
    v = b.copy()
    for j in range(m):
        K[:, j] = v
        v = A @ v
    Q, _ = np.linalg.qr(K)
    return Q

def cond_eigvecs(H):
    lam, V = np.linalg.eig(H)
    try:
        invV = np.linalg.inv(V)
    except np.linalg.LinAlgError:
        return np.inf
    normV = np.linalg.norm(V, 2)
    normInv = np.linalg.norm(invV, 2)
    return normV * normInv

def trial(n, m, p, seed=None):
    rng = np.random.default_rng(seed)
    A = hermitian_decay_matrix(n, p)
    # Random starting vector
    b = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    Q = krylov_basis(A, b, m)
    H = Q.conj().T @ A @ Q
    return cond_eigvecs(H)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Sweep condition numbers for Hermitian matrices with eigenvalue decay i^{-p}.')
    parser.add_argument('--ns', type=int, nargs='+', required=True, help='Matrix sizes')
    parser.add_argument('--m', type=int, required=True, help='Krylov subspace dimension')
    parser.add_argument('--ps', type=float, nargs='+', required=True, help='Decay exponents p')
    parser.add_argument('--seeds', type=int, nargs='+', default=[0,1,2,3,4], help='Random seeds')
    args = parser.parse_args()
    results = []
    for n in args.ns:
        for p in args.ps:
            for seed in args.seeds:
                c = trial(n, args.m, p, seed)
                results.append({"n": n, "m": args.m, "p": p, "seed": seed, "cond": float(np.real_if_close(c))})
    json.dump(results, sys.stdout)

if __name__ == '__main__':
    main()
