import numpy as np
from scipy.linalg import eigvalsh
import matplotlib.pyplot as plt
import argparse

def get_weyl_diagonal(n):
    phi = (1 + 5**0.5) / 2
    return np.array([ (i * phi) % 1 for i in range(1, n + 1)])

def compute_gap(matrix):
    evals = eigvalsh(matrix)
    gaps = np.diff(evals)
    return np.min(gaps)

def discrete_laplacian(n):
    main_diag = 2 * np.ones(n)
    off_diag = -1 * np.ones(n-1)
    return np.diag(main_diag) + np.diag(off_diag, k=1) + np.diag(off_diag, k=-1)

def random_tridiagonal(n):
    # Hermitian tridiagonal: real diagonal, complex off-diagonal (but we can use real for simplicity)
    main = np.random.randn(n)
    off = np.random.randn(n-1)
    return np.diag(main) + np.diag(off, k=1) + np.diag(off, k=-1)

def run_experiment(n_values, delta_values):
    results = []
    for n in n_values:
        # Test against a few different A matrices for each n
        matrices = [discrete_laplacian(n), random_tridiagonal(n)]
        e_diag = get_weyl_diagonal(n)
        E = np.diag(e_diag)
        
        for delta in delta_values:
            min_gap = float('inf')
            for A in matrices:
                perturbed = A + delta * E
                gap = compute_gap(perturbed)
                if gap < min_gap:
                    min_gap = gap
            results.append({'n': n, 'delta': delta, 'gap': min_gap})
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--n_range', type=int, nargs='+', default=[10, 20, 40, 80])
    parser.add_argument('--delta_range', type=float, nargs='+', default=[1e-3, 1e-2, 1e-1])
    args = parser.parse_args()

    res = run_experiment(args.n_range, args.delta_range)
    print("n,delta,gap")
    for r in res:
        print(f"{r['n']},{r['delta']},{r['gap']}")
