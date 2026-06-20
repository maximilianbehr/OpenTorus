import numpy as np
import time
from scipy.sparse.linalg import cg
import argparse

def run_cg(A, b, eps):
    """
    Compute stopping time for CG to reach relative A-norm error eps.
    ||x_t - x*||_A^2 <= eps * ||x_0 - x*||_A^2
    For x_0 = 0, this is equivalent to:
    ||x_t - x*||_A^2 <= eps * ||x*||_A^2
    """
    # A is diagonal here for simplicity in the first pass.
    # For a general SPD matrix, we'd use scipy.sparse.linalg.cg or custom loop.
    # Since A = diag(lambda), x* = b / lambda.
    # ||x*||_A^2 = sum (b_i^2 / lambda_i)
    
    lambdas = np.diag(A) if A.ndim == 2 else A
    x_star = b / lambdas
    initial_error_sq = np.sum((x_star**2) * lambdas)
    target_error_sq = eps * initial_error_sq
    
    # CG for diagonal matrix:
    # The error in A-norm after t steps is min_{P(0)=1, deg P=t} max_i |P(lambda_i)| * ||x*||_A
    # However, we can just simulate it or use the known property.
    # To be empirical and consistent with RCD, let's actually run a CG loop.
    
    x = np.zeros_like(b)
    r = b - A @ x if A.ndim == 2 else b - lambdas * x
    p = r.copy()
    rsold = np.dot(r, r)
    
    for t in range(1, len(b) + 1):
        Ap = A @ p if A.ndim == 2 else lambdas * p
        alpha = rsold / np.dot(p, Ap)
        x += alpha * p
        r -= alpha * Ap
        rsnew = np.dot(r, r)
        
        # Check A-norm error: ||x_t - x*||_A^2 = (x-x*)^T A (x-x*)
        # For diagonal A, this is sum (x_i - b_i/lambda_i)^2 * lambda_i
        # = sum (x_i * lambda_i - b_i)^2 / lambda_i = ||r_t||_{A^-1}^2
        # But we can also compute it as:
        current_error_sq = np.sum(((x - x_star)**2) * lambdas)
        if current_error_sq <= target_error_sq:
            return t
        
        p = r + (rsnew / rsold) * p
        rsold = rsnew
    return len(b)

def run_rcd(A, b, eps):
    """
    Compute stopping time for Randomized Coordinate Descent.
    Update: x_{k+1} = x_k + ((b - A x_k)_i / A_{ii}) e_i
    """
    lambdas = np.diag(A) if A.ndim == 2 else A
    x_star = b / lambdas
    initial_error_sq = np.sum((x_star**2) * lambdas)
    target_error_sq = eps * initial_error_sq
    
    x = np.zeros_like(b)
    n = len(b)
    
    # To avoid infinite loops in case of slow convergence, set a cap
    max_iter = 10**7 
    
    for t in range(1, max_iter):
        i = np.random.randint(0, n)
        # Update x_i: (b - A x)_i / A_{ii}
        # For diagonal A: (b_i - lambda_i * x_i) / lambda_i = b_i/lambda_i - x_i
        delta = (b[i] / lambdas[i]) - x[i]
        x[i] += delta
        
        # Check A-norm error every few iterations to save time
        if t % 100 == 0 or t < 100:
            current_error_sq = np.sum(((x - x_star)**2) * lambdas)
            if current_error_sq <= target_error_sq:
                return t
    return max_iter

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--p", type=float, required=True)
    parser.add_argument("--eps", type=float, default=1e-4)
    parser.add_argument("--trials", type=int, default=10)
    args = parser.parse_args()

    # Eigenvalues lambda_i = i^-p for i=1...n
    lambdas = np.arange(1, args.n + 1)**(-args.p)
    A = np.diag(lambdas)
    
    t_cg_list = []
    t_rcd_list = []
    
    for _ in range(args.trials):
        b = np.random.randn(args.n)
        
        t_cg = run_cg(A, b, args.eps)
        t_rcd = run_rcd(A, b, args.eps)
        
        t_cg_list.append(t_cg)
        t_rcd_list.append(t_rcd)
        
    print(f"n={args.n}, p={args.p}, eps={args.eps}")
    print(f"avg_t_cg={np.mean(t_cg_list):.2f}")
    print(f"avg_t_rcd={np.mean(t_rcd_list):.2f}")
    print(f"ratio={np.mean(t_rcd_list)/np.mean(t_cg_list):.2f}")

if __name__ == "__main__":
    main()
