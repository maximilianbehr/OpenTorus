import numpy as np

def get_kappa_v(H):
    try:
        vals, vecs = np.linalg.eig(H)
        return np.linalg.cond(vecs)
    except Exception:
        return np.nan

def run_experiment(A, m, b):
    n = A.shape[0]
    K = np.zeros((n, m), dtype=complex)
    v = b / np.linalg.norm(b)
    K[:, 0] = v
    for i in range(1, m):
        w = A @ K[:, i-1]
        for j in range(i):
            w -= np.vdot(K[:, j], w) * K[:, j]
        norm_w = np.linalg.norm(w)
        if norm_w < 1e-12:
            return np.nan
        K[:, i] = w / norm_w
    
    Q = K
    H = Q.conj().T @ A @ Q
    return get_kappa_v(H)

def generate_grcar(n):
    # Grcar matrix: a known highly non-normal matrix
    A = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            A[i, j] = (i + 1) * (j - i) / (j * (j + 1))
    return A

def sweep_matrix(name, A_gen, ns, ms, trials=20):
    print(f"--- Sweeping {name} ---")
    results = []
    for n in ns:
        A = A_gen(n)
        for m in ms:
            if m > n: continue
            kappas = []
            for _ in range(trials):
                b = np.random.randn(n) + 1j * np.random.randn(n)
                kappa = run_experiment(A, m, b)
                if not np.isnan(kappa):
                    kappas.append(kappa)
            avg_kappa = np.mean(kappas) if kappas else np.nan
            results.append((n, m, avg_kappa))
            print(f"n={n}, m={m}, avg_kappa={avg_kappa:.2e}")
    return results

if __name__ == "__main__":
    ns = [20, 40, 80, 160]
    ms = [5, 10, 20, 40]
    
    # Jordan Block
    jordan_gen = lambda n: np.diag(np.ones(n-1), k=1).astype(complex)
    sweep_matrix("Jordan Block", jordan_gen, ns, ms)
    
    # Grcar Matrix
    sweep_matrix("Grcar Matrix", generate_grcar, ns, ms)
    
    # Random Upper Triangular (clustered diag)
    def random_upper_gen(n):
        diag = np.random.randn(n) * 0.1
        A = np.triu(np.random.randn(n, n) + 1j * np.random.randn(n, n))
        np.fill_diagonal(A, diag)
        return A
    sweep_matrix("Random Upper", random_upper_gen, ns, ms)
