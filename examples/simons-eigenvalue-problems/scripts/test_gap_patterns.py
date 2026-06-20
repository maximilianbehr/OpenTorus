import numpy as np
from scipy.linalg import eigvalsh
import matplotlib.pyplot as plt
import argparse

def van_der_corput(n):
    """Generates a Van der Corput sequence in base 2."""
    res = []
    for i in range(1, n + 1):
        f = 0
        denom = 2
        temp_i = i
        while temp_i > 0:
            f += (temp_i % 2) / denom
            temp_i //= 2
            denom *= 2
        res.append(f)
    return np.array(res)

def get_diagonal_pattern(name, n):
    if name == 'linear':
        return np.linspace(0, 1, n)
    elif name == 'cosine':
        theta = np.pi * (1 + 5**0.5) / 2  # Golden ratio based theta
        return (np.cos(np.arange(n) * theta) + 1) / 2
    elif name == 'vdc':
        return van_der_corput(n)
    else:
        raise ValueError(f"Unknown pattern {name}")

def create_tridiagonal(type, n):
    if type == 'laplacian':
        # Discrete Laplacian: 2 on diag, -1 on off-diag
        A = np.eye(n) * 2
        off_diag = -np.ones(n - 1)
        return np.diag(off_diag, k=1) + np.diag(off_diag, k=-1) + A
    elif type == 'random':
        # Random Hermitian tridiagonal
        diag = np.random.randn(n)
        off_diag = np.random.randn(n - 1) + 1j * np.random.randn(n - 1)
        A = np.diag(diag) + np.diag(off_diag, k=1) + np.diag(np.conj(off_diag), k=-1)
        return A
    else:
        raise ValueError(f"Unknown matrix type {type}")

def compute_gap(A, delta, pattern_name):
    n = A.shape[0]
    E = np.diag(get_diagonal_pattern(pattern_name, n))
    M = A + delta * E
    evals = eigvalsh(M)
    return np.min(np.diff(evals))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n_values', type=int, nargs='+', default=[10, 20, 40, 80])
    parser.add_argument('--delta_values', type=float, nargs='+', default=[1e-3, 1e-2, 1e-1, 1.0])
    parser.add_argument('--matrix_types', type=str, nargs='+', default=['laplacian', 'random'])
    parser.add_argument('--patterns', type=str, nargs='+', default=['linear', 'cosine', 'vdc'])
    args = parser.parse_args()

    results = []

    for m_type in args.matrix_types:
        for pattern in args.patterns:
            for n in args.n_values:
                # For random, we should average over a few trials or take the worst case
                # Here we do 5 trials and take the minimum gap to be conservative
                gaps = []
                for _ in range(5):
                    A = create_tridiagonal(m_type, n)
                    for delta in args.delta_values:
                        gap = compute_gap(A, delta, pattern)
                        gaps.append((delta, gap))
                
                # For laplacian, A is deterministic, so we just take the first one
                if m_type == 'laplacian':
                    A = create_tridiagonal('laplacian', n)
                    for delta in args.delta_values:
                        gap = compute_gap(A, delta, pattern)
                        results.append({'matrix': m_type, 'pattern': pattern, 'n': n, 'delta': delta, 'gap': gap})
                else:
                    # For random, we'll just store the trials for now or average them
                    for trial in range(5):
                        A = create_tridiagonal('random', n)
                        for delta in args.delta_values:
                            gap = compute_gap(A, delta, pattern)
                            results.append({'matrix': m_type, 'pattern': pattern, 'n': n, 'delta': delta, 'gap': gap})

    # Print results as CSV for easy analysis
    print("matrix,pattern,n,delta,gap")
    for r in results:
        print(f"{r['matrix']},{r['pattern']},{r['n']},{r['delta']},{r['gap']}")

if __name__ == "__main__":
    main()
