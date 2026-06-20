import numpy as np
from scipy.linalg import eigvalsh

def get_ramp_perturbation(n):
    """Returns a diagonal matrix E where E_ii = i/n."""
    return np.diag(np.arange(1, n + 1) / n)

def get_discrete_laplacian(n):
    """Returns the 1D discrete Laplacian matrix."""
    main_diag = 2 * np.ones(n)
    off_diag = -1 * np.ones(n - 1)
    return np.diag(main_diag) + np.diag(off_diag, k=1) + np.diag(off_diag, k=-1)

def get_random_hermitian_tridiagonal(n):
    """Returns a random Hermitian tridiagonal matrix."""
    diag = np.random.randn(n)
    off_diag = np.random.randn(n - 1) + 1j * np.random.randn(n - 1)
    A = np.diag(diag) + np.diag(off_diag, k=1) + np.diag(off_diag.conj(), k=-1)
    return A

def compute_gap(matrix):
    """Computes the minimum gap between adjacent eigenvalues."""
    evs = eigvalsh(matrix)
    gaps = np.diff(evs)
    return np.min(gaps)

def run_experiment():
    n_values = [10, 20, 50]
    delta_values = [1e-4, 1e-2, 1e-1, 1.0]
    matrix_types = ["zero", "laplacian", "random"]
    
    results = []

    for n in n_values:
        # Prepare matrices
        A_zero = np.zeros((n, n))
        A_lap = get_discrete_laplacian(n)
        A_rand = get_random_hermitian_tridiagonal(n)
        E = get_ramp_perturbation(n)
        
        matrices = {"zero": A_zero, "laplacian": A_lap, "random": A_rand}
        
        for m_type in matrix_types:
            A = matrices[m_type]
            for delta in delta_values:
                perturbed = A + delta * E
                gap = compute_gap(perturbed)
                results.append({
                    "n": n,
                    "delta": delta,
                    "type": m_type,
                    "gap": gap,
                    "ratio": gap / (delta/n) if delta != 0 else 0
                })

    print("n,delta,type,gap,ratio")
    for r in results:
        print(f"{r['n']},{r['delta']},{r['type']},{r['gap']:.6e},{r['ratio']:.4f}")

if __name__ == "__main__":
    run_experiment()
