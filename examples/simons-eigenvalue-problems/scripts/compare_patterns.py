import numpy as np
from scipy.linalg import eigvalsh

def get_ramp(n):
    return np.arange(1, n + 1) / n

def get_golden_ratio_seq(n):
    phi = (1 + 5**0.5) / 2
    return (np.arange(n) * phi) % 1

def get_discrete_laplacian(n):
    main_diag = 2 * np.ones(n)
    off_diag = -1 * np.ones(n - 1)
    return np.diag(main_diag) + np.diag(off_diag, k=1) + np.diag(off_diag, k=-1)

def get_random_hermitian_tridiagonal(n):
    diag = np.random.randn(n)
    off_diag = np.random.randn(n - 1) + 1j * np.random.randn(n - 1)
    A = np.diag(diag) + np.diag(off_diag, k=1) + np.diag(off_diag.conj(), k=-1)
    return A

def compute_gap(matrix):
    evs = eigvalsh(matrix)
    return np.min(np.diff(evs))

def run_experiment():
    n_values = [20, 50, 100]
    delta_values = [1e-3, 1e-1, 1.0]
    patterns = ["ramp", "golden"]
    matrix_types = ["laplacian", "random"]
    
    print("n,delta,type,pattern,gap,ratio")
    for n in n_values:
        A_lap = get_discrete_laplacian(n)
        A_rand = get_random_hermitian_tridiagonal(n)
        matrices = {"laplacian": A_lap, "random": A_rand}
        
        for m_type in matrix_types:
            A = matrices[m_type]
            for delta in delta_values:
                for pat in patterns:
                    if pat == "ramp":
                        E_diag = get_ramp(n)
                    else:
                        E_diag = get_golden_ratio_seq(n)
                    
                    perturbed = A + delta * np.diag(E_diag)
                    gap = compute_gap(perturbed)
                    ratio = gap / (delta/n) if delta != 0 else 0
                    print(f"{n},{delta},{m_type},{pat},{gap:.6e},{ratio:.4f}")

if __name__ == "__main__":
    run_experiment()
