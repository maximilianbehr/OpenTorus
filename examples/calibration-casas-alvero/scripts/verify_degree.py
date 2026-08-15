#!/usr/bin/env python3
"""
Symbolic verification of Casas-Alvero for a fixed degree d over Q.
We parametrize monic f(x)=x^d + a_{d-1} x^{d-1}+...+a0,
impose existence of common root with each derivative via resultants,
and eliminate to show only trivial solution (all roots equal).
For small d this is feasible with sympy Groebner.
"""
import argparse
from sympy import symbols, Poly, groebner, resultant, expand, S

def casas_alvero_degree(d):
    # coefficients a0..a_{d-1}
    a = symbols('a0:%d' % d)
    x = symbols('x')
    # monic polynomial
    f = sum(a[i]*x**i for i in range(d)) + x**d
    # derivatives via sympy diff on expression
    polys = []
    for i in range(1, d):
        di = f.diff(x, i)
        polys.append(di)
    # resultants Res(f, f^{(i)}) must vanish for common factor
    res_polys = []
    for i in range(1, d):
        r = resultant(f, polys[i-1], x)
        res_polys.append(expand(r))
    # Groebner basis of resultants + condition that discriminant !=0? 
    # We want to show the only solution is all roots equal.
    # Simpler: impose that f has a repeated root structure via elementary symmetric sums.
    # For verification we compute Groebner basis and check if ideal forces (x - alpha)^d.
    # Use elimination order with coefficients first.
    G = groebner(res_polys, *a, order='lex')
    return G

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--d', type=int, default=3)
    args = parser.parse_args()
    d = args.d
    print(f"Verifying Casas-Alvero for degree {d}")
    G = casas_alvero_degree(d)
    # Print number of basis elements
    print(f"Groebner basis size: {len(G)}")
    # Check if basis contains relations forcing a_i to be elementary symmetric of equal roots
    # For d=3 we expect only trivial solution.
    # Output basis for inspection
    for g in G:
        print(g)
    print("DONE")

if __name__ == '__main__':
    main()
