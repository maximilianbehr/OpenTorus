import numpy as np
import numpy.linalg as la
import argparse, json, sys

def krylov_subspace(A, v0, m):
    """Return orthonormal basis Q of Krylov subspace K_m(A,v0)."""
    n = A.shape[0]
    Q = np.zeros((n, m))
    w = v0 / la.norm(v0)
    for j in range(m):
        Q[:, j] = w
        w = A @ w
        # orthogonalize against previous Q columns (modified Gram-Schmidt)
        for k in range(j+1):
            proj = np.dot(Q[:, k], w)
            w -= proj * Q[:, k]
        norm = la.norm(w)
        if norm < 1e-12:
            # early termination
            return Q[:, :j+1]
        w /= norm
    return Q

def ritz_vectors(A, Q):
    """Compute Ritz eigenpairs of A projected onto subspace spanned by Q.
    Returns eigenvectors in the original space (Q @ y) and eigenvalues.
    """
    T = Q.T @ A @ Q  # small m x m matrix
    evals, evecs_small = la.eig(T)
    ritz_vecs = Q @ evecs_small
    return evals, ritz_vecs

def condition_numbers(vecs):
    """Return array of condition numbers (2-norm) for each eigenvector.
    Condition number defined as ||v|| * ||v^{-1}||? Here we use ratio of max/min entry magnitude.
    For simplicity, use 2-norm of vector and its inverse in the subspace of that vector? We'll approximate by
    cond = norm(v) * norm(v) / (abs(np.dot(v, v))) which equals norm(v)^2 / ||v||_2^2 = 1. Not useful.
    Instead compute condition number of eigenvector matrix V (columns are vectors).
    """
    # Compute condition numbers of each column as norm(v) * norm(e_i) where e_i is unit vector in direction of v? We'll use
    # cond_i = ||v_i||_2 * ||v_i||_inf / min(abs(v_i)) to capture spread.
    conds = []
    for v in vecs.T:
        norm2 = la.norm(v)
        max_abs = np.max(np.abs(v))
        min_abs = np.min(np.abs(v[np.abs(v) > 1e-12])) if np.any(np.abs(v) > 1e-12) else 1e-12
        cond = norm2 * max_abs / min_abs
        conds.append(float(cond))
    return np.array(conds)

def run_one(n, m, seed):
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n))
    # make symmetric to have real eigenvalues (optional)
    A = (A + A.T) / 2.0
    v0 = rng.standard_normal(n)
    Q = krylov_subspace(A, v0, m)
    evals, ritz_vecs = ritz_vectors(A, Q)
    conds = condition_numbers(ritz_vecs)
    return {
        "n": n,
        "m": m,
        "seed": seed,
        "cond_mean": float(np.mean(conds)),
        "cond_max": float(np.max(conds)),
        "cond_min": float(np.min(conds))
    }

def main():
    parser = argparse.ArgumentParser(description="Sweep condition numbers of Ritz vectors over n,m.")
    parser.add_argument('--ns', type=int, nargs='+', required=True, help='List of matrix sizes n')
    parser.add_argument('--ms', type=int, nargs='+', required=True, help='List of Krylov dimensions m')
    parser.add_argument('--seeds', type=int, nargs='+', default=[0,1,2,3,4], help='Random seeds')
    args = parser.parse_args()
    results = []
    for n in args.ns:
        for m in args.ms:
            for seed in args.seeds:
                res = run_one(n, m, seed)
                results.append(res)
    json.dump(results, sys.stdout)

if __name__ == "__main__":
    main()
