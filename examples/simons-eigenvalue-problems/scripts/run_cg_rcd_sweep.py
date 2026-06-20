import numpy as np
import argparse
from cg_vs_rcd import run_cg, run_rcd

def main():
    # Parameters for the sweep
    n_values = [64, 128, 256, 512]
    p_values = [0.5, 1.0, 2.0]
    eps = 1e-4
    trials = 15

    results = []

    for p in p_values:
        print(f"Running sweep for p={p}...")
        for n in n_values:
            t_cg_all = []
            t_rcd_all = []
            
            # Eigenvalues lambda_i = i^-p
            lambdas = np.arange(1, n + 1)**(-p)
            A = np.diag(lambdas)
            
            for trial in range(trials):
                b = np.random.randn(n)
                
                t_cg = run_cg(A, b, eps)
                t_rcd = run_rcd(A, b, eps)
                
                t_cg_all.append(t_cg)
                t_rcd_all.append(t_rcd)
            
            avg_cg = np.mean(t_cg_all)
            avg_rcd = np.mean(t_rcd_all)
            ratio = avg_rcd / avg_cg
            
            results.append({
                'n': n,
                'p': p,
                'avg_cg': avg_cg,
                'avg_rcd': avg_rcd,
                'ratio': ratio
            })
            print(f"  n={n}: CG={avg_cg:.1f}, RCD={avg_rcd:.1f}, Ratio={ratio:.2f}")

    # Print final table
    print("\nSummary Table:")
    print("p\tn\tAvg CG\tAvg RCD\tRatio")
    for res in results:
        print(f"{res['p']}\t{res['n']}\t{res['avg_cg']:.1f}\t{res['avg_rcd']:.1f}\t{res['ratio']:.2f}")

if __name__ == "__main__":
    main()
