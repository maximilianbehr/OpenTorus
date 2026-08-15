#!/usr/bin/env python3
"""
Search for a 5x5 doubly stochastic counterexample to Perfect-Mirsky.
Parametrize via convex combination of permutation matrices and test eigenvalues.
"""
import numpy as np, itertools, math, random
from numpy.linalg import eigvals

def random_doubly_stochastic(n):
    # Birkhoff-von Neumann: random convex combo of permutations
    perms = list(itertools.permutations(range(n)))
    k = 20
    coeffs = np.random.dirichlet(np.ones(k))
    mats = []
    for i in range(k):
        p = random.choice(perms)
        M = np.zeros((n,n))
        for r,c in enumerate(p):
            M[r,c]=1.0
        mats.append(M)
    return sum(c*m for c,m in zip(coeffs,mats))

def point_in_convex_hull(z, roots):
    # check if z in convex hull of roots via barycentric? Use linear programming approx.
    # For small k, use simple check: z is in polygon if it can be expressed as convex combo.
    # We'll approximate by checking if z lies inside polygon using winding number for regular polygon.
    # For convex hull of roots of unity, it's a regular polygon centered at 0.
    # Compute max radius in direction of angle.
    theta = np.angle(z)
    r = abs(z)
    # For k-th roots, the radial boundary is cos(pi/k)/cos(theta mod 2pi/k - pi/k) etc.
    # Simpler: sample many points on polygon and check via linear programming using scipy? Use brute force linear programming with cvxopt not available.
    # We'll use a simple heuristic: for each k, compute max radius of polygon in direction theta.
    # For regular polygon with vertices e^{2pi i/k}, the support function is cos(delta)/cos(pi/k) where delta = angle mod 2pi/k - pi/k.
    # Actually radial boundary r_max(theta) = cos(pi/k)/cos( (theta mod 2pi/k) - pi/k ) if |...| <= pi/k else inf? Wait polygon is bounded.
    # Let's compute via linear programming using numpy least squares with constraints sum w=1, w>=0.
    # Use simple check: solve for weights via linear programming approximated by checking if z is in convex hull of points.
    # We'll use scipy.optimize.linprog if available.
    try:
        from scipy.optimize import linprog
        m = len(roots)
        c = np.zeros(m)
        A_eq = np.vstack([np.real(roots), np.imag(roots), np.ones(m)])
        b_eq = np.array([z.real, z.imag, 1.0])
        bounds = [(0,1)]*m
        res = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method='highs')
        return res.success
    except Exception:
        # fallback heuristic
        return False

def is_inside_union(z):
    for k in range(2,6):
        roots = np.exp(2j*np.pi*np.arange(k)/k)
        if point_in_convex_hull(z, roots):
            return True
    return False

def search(num_trials=20000):
    best = None
    best_dist = -1
    for _ in range(num_trials):
        M = random_doubly_stochastic(5)
        ev = eigvals(M)
        for z in ev:
            if not is_inside_union(z):
                # candidate
                return M, z
    return None, None

if __name__ == "__main__":
    M,z = search(5000)
    print("Found" if M is not None else "None")
    if M is not None:
        print(M)
        print("eigenvalue", z)
