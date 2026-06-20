import numpy as np
from scipy.linalg import eigvalsh
import argparse
import json

def get_diagonal_pattern(name, n):
    if name == "ramp":
        return np.linspace(0, 1, n)
    elif name == "golden":
        phi = (1 + 5**0.5) / 2
        return np.array([ (i * phi) % 1 for i in range(n)])
    elif name == "cos":
        theta = np.pi * (1 + 5**0.5) / 2 # Irrational multiple of pi
        return np.cos(np.arange(n) * theta)
    else:
        raise ValueError(f"Unknown pattern {name}")

def get_tridiagonal_matrix(type, n):
    if type == "zero":
        return np.zeros((n, n))
    elif type == "laplacian":
        # Standard 1D Laplacian: -1 on off-diagonals, 2 on diagonal
        A = np.zeros((n, n))
        np.fill_diagonal(A, 2)
        for i in range(n-1):
            A[i, i+1] = A[i+1, i] = -1
        return A
    elif type == "random":
        # Random Hermitian tridiagonal
        diag = np.random.randn(n)
        off_diag = np.random.randn(n-1) + 1j * np.random.randn(n-1)
        A = np.diag(diag) + np.diag(off_diag, k=1) + np.diag(off_diag.conj(), k=-1)
        return A.real # Problem says Hermitian tridiagonal; keeping it real for simplicity unless needed
    else:
        raise ValueError(f"Unknown matrix type {type}")

def compute_gap(A, delta, pattern_name):
    n = A.shape[0]
    E = np.diag(get_diagonal_pattern(pattern_name, n))
    perturbed = A + delta * E
    evs = eigvalsh(perturbed)
    gaps = np.diff(evs)
    return np.min(gaps)

def run_sweep(matrix_type, pattern_name, ns, deltas):
    results = []
    for n in ns:
        A = get_tridiagonal_matrix(matrix_type, n)
        for delta in deltas:
            gap = compute_gap(A, delta, pattern_name)
            results.append({
                "n": n,
                "delta": delta,
                "gap": gap,
                "matrix_type": matrix_type,
                "pattern": pattern_name
            })
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_range", type=int, nargs='+', default=[10, 20, 40, 80])
    parser.add_argument("--delta_range", type=float, nargs='+', default=[1e-4, 1e-3, 1e-2, 1e-1, 1.0])
    parser.add_argument("--matrix_types", type=str, nargs='+', default=["zero", "laplacian", "random"])
    parser.add_argument("--patterns", type=str, nargs='+', default=["ramp", "golden", "cos"])
    args = parser.parse_args()

    all_results = []
    for mt in args.matrix_types:
        for pt in args.patterns:
            res = run_sweep(mt, pt, args.n_range, args.delta_range)
            all_results.extend(res)

    with open("gap_results.json", "w") as f:
        json.dump(all_results, f)
    
    print(f"Completed sweep. Results saved to gap_results.json")
