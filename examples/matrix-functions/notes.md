# Problem: Optimal restart length for restarted Arnoldi methods for f(A)b

Restarted Arnoldi / limited-memory polynomial methods approximate $f(A)\,b$ for a large matrix
$A \in \mathbb{C}^{n\times n}$ using cycles of fixed Krylov length $m$ (the memory budget).
Empirically, convergence of the restarted iteration depends non-monotonically on $m$: shorter
restart cycles sometimes converge faster than longer ones, contrary to the intuition that a
larger subspace is always better.

Characterize — or predict from cheaply observable quantities — the restart length $m$ that
minimizes total work to reach a target accuracy, for a given $f$ (e.g. $\exp$, $\sqrt{\cdot}$,
$\log$, $z^{-1/2}$) and matrix class. Is there a regime where shorter cycles are provably
superior, and can the non-monotone dependence on $m$ be explained? Numerically explorable:
sweep $m$ against iterations/flops to tolerance for several $f$ and matrix families.
Source: arXiv:2002.01682, Sec. 4.

# Problem: A posteriori error estimation for limited-memory f(A)b approximations

Limited-memory methods produce an approximation $x_k \approx f(A)\,b$ without storing the full
Krylov basis, so the usual residual/error indicators are unavailable or unreliable. A robust,
cheap, and provable a posteriori error estimate (a computable stopping criterion) for the
restarted Arnoldi approximation to $f(A)\,b$ — valid for general, possibly non-normal $A$ — is
not available in general.

Derive a computable estimate $\eta_k$ with $\eta_k \approx \lVert f(A)b - x_k\rVert$ (or a
guaranteed upper bound) for restarted/limited-memory polynomial methods, and characterize when
it is reliable. Numerically explorable: test candidate estimators against the true error across
$f$ and matrix ensembles. Source: arXiv:2002.01682, Sec. 4.1.

# Problem: Efficient and stable evaluation of the first column of f(H_m)

Each cycle of a restarted Arnoldi method for $f(A)\,b$ requires the action $f(H_m)\,e_1$, where
$H_m \in \mathbb{C}^{m\times m}$ is the small Hessenberg/tridiagonal projection. Forming the
dense matrix function $f(H_m)$ only to read off its first column costs $O(m^3)$ per cycle and can
be numerically delicate for non-normal $H_m$.

Can $f(H_m)\,e_1$ (the only quantity needed) be computed more efficiently and stably than by
forming all of $f(H_m)$, especially across the sequence of growing/updated $H_m$ produced by
successive restarts? The survey states this remains open. Numerically explorable: compare
cost and accuracy of candidate schemes. Source: arXiv:2002.01682, Sec. 4.1.

# Problem: Controlling loss of orthogonality in two-pass Lanczos for f(A)b

For Hermitian $A$, two-pass Lanczos computes $f(A)\,b$ with $O(1)$ vectors of storage by
re-generating the Krylov basis on a second pass instead of storing it. Without
reorthogonalization, loss of orthogonality introduces spurious Ritz values and can delay
convergence relative to the full-memory method.

Quantify the convergence delay of two-pass / non-reorthogonalized limited-memory Lanczos for
$f(A)\,b$ as a function of the spectrum of $A$ and of $f$, and design a limited-memory scheme
that provably controls it. Numerically explorable: measure the delay against spectral gaps and
eigenvalue clustering. Source: arXiv:2002.01682, Sec. 4.

# Problem: Spectrum-adaptive explicit polynomial methods without a priori bounds

Explicit polynomial methods (e.g. Chebyshev or other interpolation-based approximations of $f$)
applied to $f(A)\,b$ require, a priori, a region containing the spectrum of $A$ in order to fix
the polynomial degree and the approximation interval/nodes. Obtaining tight spectral bounds in
advance is often impractical.

Design an explicit polynomial method that adapts the degree and the approximation region from
observed Arnoldi/Lanczos data during the iteration — with convergence guarantees and without a
priori spectral bounds — matching the efficiency of methods given exact bounds. Numerically
explorable: compare adaptive versus oracle-bound degree selection. Source: arXiv:2002.01682,
Sec. 3.
