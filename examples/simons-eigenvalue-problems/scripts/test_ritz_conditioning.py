import numpy as np

def get_kappa_v(H):
    # H is m x m. Ritz values are eigenvalues of H.
    # kappa_V(H) = ||V|| * ||V^-1|| where V is the eigenvector matrix.
    try:
        vals, vecs = np.linalg.eig(H)
        # Condition number of the eigenvector matrix
        return np.linalg.cond(vecs)
    except Exception as e:
        return np.nan

def run_experiment(A, m, b):
    n = A.shape[0]
    # Construct Krylov subspace K_m(A, b)
    # Q is n x m orthonormal basis
    K = np.zeros((n, m), dtype=complex)
    v = b / np.linalg.norm(b)
    K[:, 0] = v
    for i in range(1, m):
        w = A @ K[:, i-1]
        # Gram-Schmidt (simple version for small n)
        for j in range(i):
            w -= np.vdot(K[:, j], w) * K[:, j]
        norm_w = np.linalg.norm(w)
        if norm_w < 1e-12:
            # Subspace collapsed
            return np.nan
        K[:, i] = w / norm_w
    
    Q = K
    H = Q.conj().T @ A @ Q
    return get_kappa_v(H)

def test_jordan_block(n, m, trials=10):
    # Single Jordan block: 1s on first superdiagonal, 0 elsewhere
    A = np.diag(np.ones(n-1), k=1).astype(complex)
    kappas = []
    for _ in range(trials):
        b = np.random.randn(n) + 1j * np.random.randn(n)
        kappa = run_experiment(A, m, b)
        if not np.isnan(kappa):
            kappas.append(kappa)
    return np.mean(kappas) if kappas else np.nan

def test_random_upper(n, m, trials=10):
    # Random upper triangular with clustered diagonal
    diag = np.random.randn(n) * 0.1 # Clustered around 0
    A = np.triu(np.random.randn(n, n) + 1j * np.random.randn(n, n))
    np.fill_diagonal(A, diag)
    kappas = []
    for _ in range(trials):
        b = np.random.randn(n) + 1j * np.random.randn(n)
        kappa = run_experiment(A, m, b)
        if not np.isnan(kappa):
            kappas.append(kappa)
    return np.mean(kappas) if kappas else np.nan

if __name__ == "__main__":
    ns = [10, 20, 40, 80]
    ms = [5, 10, 20] # m < n usually
    
    print("Testing Jordan Block:")
    for n in ns:
        for m in ms:
            if m <= n:
                res = test_jordan_block(n, m)
                print(f"n={n}, m={m}, avg_kappa={res:.2e}")

    print("\nTesting Random Upper Triangular:")
    for n in ns:
        for m in ms:
            if m <= n:
                res = test_random_upper(n, m)
                print(f"n={n}, m={m}, avg_kappa={res:.2e}")
