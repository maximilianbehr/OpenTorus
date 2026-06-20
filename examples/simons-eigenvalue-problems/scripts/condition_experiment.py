import numpy as np, json, sys

def krylov_basis(A, b, m):
    n = A.shape[0]
    Q = np.zeros((n, m), dtype=A.dtype)
    v = b / np.linalg.norm(b)
    for j in range(m):
        Q[:, j] = v
        w = A @ v
        for i in range(j + 1):
            w -= np.vdot(Q[:, i], w) * Q[:, i]
        if j < m - 1:
            norm_w = np.linalg.norm(w)
            if norm_w < 1e-12:
                return Q[:, :j+1]
            v = w / norm_w
    return Q

def cond_eigvecs(H):
    lam, V = np.linalg.eig(H)
    try:
        return np.linalg.cond(V, p=2)
    except np.linalg.LinAlgError:
        return np.inf

def get_matrix(family, n, rng):
    if family == 'random':
        return rng.standard_normal((n, n)) + 1j*rng.standard_normal((n, n))
    elif family == 'jordan':
        A = np.eye(n)
        for i in range(n - 1):
            A[i, i+1] = 1.0
        return A
    elif family == 'grcar':
        A = np.zeros((n, n))
        for i in range(n):
            A[i, i] = (i + 1) / n
            if i < n - 1:
                A[i, i+1] = 1.0
        return A
    else:
        raise ValueError(f"Unknown family {family}")

def trial(family, n, m, seed=None):
    rng = np.random.default_rng(seed)
    A = get_matrix(family, n, rng)
    b = rng.standard_normal(n) + 1j*rng.standard_normal(n)
    Q = krylov_basis(A, b, m)
    actual_m = Q.shape[1]
    H = Q.conj().T @ A @ Q
    return cond_eigvecs(H), actual_m

def main(args=None):
    families = ['random', 'jordan', 'grcar']
    ns = [40, 80, 160]
    # Test both fixed m and scaling m
    configs = [
        {"name": "fixed_m", "m_func": lambda n: 10},
        {"name": "scaling_m", "m_func": lambda n: n // 4}
    ]
    trials_per_config = 20

    all_results = {}
    for family in families:
        family_res = {}
        for cfg in configs:
            cfg_name = cfg["name"]
            family_res[cfg_name] = []
            for n in ns:
                m = cfg["m_func"](n)
                vals = []
                valid_trials = 0
                for t in range(trials_per_config):
                    c, actual_m = trial(family, n, m, seed=t)
                    if actual_m == m:
                        vals.append(float(np.real_if_close(c)))
                        valid_trials += 1
                median_cond = np.median(vals) if vals else np.nan
                family_res[cfg_name].append({"n": n, "m": m, "median_cond": median_cond, "valid": valid_trials})
        all_results[family] = family_res

    print(json.dumps(all_results, indent=2))

if __name__ == "__main__":
    main()
