# Literature Survey: Polynomial Hirsch Conjecture (PROBLEM-0001)

## Overview
The goal of this survey was to investigate the current state of the Polynomial Hirsch Conjecture, which asks whether the combinatorial diameter of a $d$-dimensional polytope with $n$ facets is bounded by a polynomial $p(n, d)$.

## Key Findings

### 1. Status of the Linear Hirsch Conjecture
- **Refuted**: The original conjecture that the diameter is at most $n-d$ was disproven by Santos (2010) [PAPER-0001].
- **Counterexample**: A 43-dimensional polytope with 86 facets and diameter $\ge 44$.

### 2. General Upper Bounds
- **Quasi-polynomial**: The best known general upper bound is quasi-polynomial.
- **Current Bound**: The bound $(n-d)\log d$ is an improvement over the original Kalai-Kleitman bound [PAPER-0007].

### 3. Evidence for Polynomial Bounds
- **Tail Bounds**: Research on "tail-quasipolynomial" bounds [PAPER-0008] suggests that for a fixed dimension $d$, the diameter is eventually bounded by $n^{1+\epsilon}$, providing strong evidence that a polynomial bound exists.

### 4. Results for Special Classes
- **Network-flow Polytopes**: The Hirsch bound ($n-d$) is satisfied [PAPER-0006].
- **Transportation Polytopes**: 
    - $3 \times N$ transportation polytopes satisfy the Hirsch bound [PAPER-0014].
    - $2 \times N$ transportation polytopes satisfy the monotone Hirsch conjecture [PAPER-0014].

### 5. Theoretical Constraints and Connections
- **Simplicial Complexes**: The maximum diameter of simplicial $d$-complexes with $n$ vertices is $n^{\Theta(d)}$ [PAPER-0003], implying that polynomial bounds for polytopes cannot be derived from general simplicial complex theory.
- **Circuit Diameter**: The concept of "circuit diameter" [PAPER-0013] provides a framework for analyzing paths that are not restricted to edges of the polytope, offering a different approach to the diameter problem.

## Summary of Parsed Artifacts
- **PAPER-0001**: Santos's counterexample to linear Hirsch.
- **PAPER-0003**: Diameter of simplicial complexes.
- **PAPER-0006**: Hirsch bound for network-flow polytopes.
- **PAPER-0007**: $(n-d)\log d$ upper bound.
- **PAPER-0008**: Tail bounds and evidence for polynomial Hirsch.
- **PAPER-0011**: Connectivity of polytope skeleta.
- **PAPER-0012**: Context on combinatorial geometry.
- **PAPER-0013**: Circuit diameter and sign-compatibility.
- **PAPER-0014**: Transportation polytopes.
- **PAPER-0018**: General survey of the conjecture.
