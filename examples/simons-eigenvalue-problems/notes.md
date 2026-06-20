# Simons workshop open problems (arXiv:2602.05394)

Five small-dimensional, numerically explorable open problems from
"Linear Systems and Eigenvalue Problems: Open Questions from a Simons Workshop".
Each section becomes one OpenTorus dossier via `opentorus problem new --from-markdown notes.md`.

# Conditioning of Ritz values from random Krylov subspaces (Problem 3.5)

Let \(A\in\mathbb{C}^{n\times n}\) be arbitrary (not necessarily normal), let \(b\) be a random
starting vector, and let \(Q\in\mathbb{C}^{n\times m}\) have orthonormal columns spanning the
Krylov subspace \(K_m(A,b)=\operatorname{span}\{b,Ab,\dots,A^{m-1}b\}\). Form \(H=Q^*AQ\), whose
eigenvalues are the Ritz values of \(A\).

## Question

Is the eigenvector-matrix condition number \(\kappa_V(H)\) bounded polynomially in \(n\) with
high probability over the random \(b\)? Equivalently, is
\(\mathbb{E}\,[\operatorname{area}\Lambda_\varepsilon(H)]\le \operatorname{poly}(n)\,\varepsilon^{\beta}\)
with \(\beta\) close to \(2\), where \(\Lambda_\varepsilon\) is the \(\varepsilon\)-pseudospectrum?

## Working hypothesis to test

For arbitrary \(A\), random-start Krylov compression regularizes the spectrum: \(\kappa_V(Q^*AQ)\)
grows at most polynomially in \(n\) with high probability, even when \(A\) is highly non-normal.

## Suggested experiments

For non-normal families (single Jordan block, random upper-triangular with clustered diagonal,
Grcar/Toeplitz) and \(n\) up to a few hundred: draw random \(b\), build the Arnoldi basis \(Q\),
form \(H=Q^*AQ\), compute \(\kappa_V(H)=\|V\|_2\|V^{-1}\|_2\), repeat over many \(b\), and fit the
growth of a high quantile of \(\kappa_V\) against \(n\) on a log-log scale. A family with clearly
super-polynomial growth is a counterexample candidate. (Seed: scripts/ritz_conditioning.py.)

# CG versus randomized coordinate descent for polynomially decaying eigenvalues (Problem 2.4)

Consider SPD systems \(A_n x = b_n\) where \(A_n\) has eigenvalues \(\lambda_i = i^{-p}\) for a fixed
exponent \(p>0\). Define stopping times
\(T_{\mathrm{CG}}(A_n,b_n,\varepsilon)=\min\{t:\|x_t-x_\star\|_A^2\le\varepsilon\|x_0-x_\star\|_A^2\}\)
for conjugate gradients, and \(T_{\mathrm{RCD}}\) analogously for randomized coordinate descent.

## Question

What is the asymptotic behaviour of \(T_{\mathrm{CG}}(A_n,b_n,\varepsilon)\) compared with
\(T_{\mathrm{RCD}}(A_n,b_n,\varepsilon)\) as \(n\to\infty\)?

## Target

Measure the scaling of both stopping times in \(n\) (and in \(p\), \(\varepsilon\)) and characterize
the ratio \(T_{\mathrm{RCD}}/T_{\mathrm{CG}}\). A clean empirical law (e.g. a power of \(n\) depending
on \(p\)) is the deliverable; this is evidence-gathering, not a proof.

## Suggested experiments

Build \(A_n=\operatorname{diag}(i^{-p})\) (or with a random orthogonal rotation), several
right-hand sides, and \(n\) over a geometric grid. Run CG and randomized coordinate descent to a
fixed relative \(A\)-norm tolerance, record both stopping times, average over right-hand sides,
and fit \(\log T\) against \(\log n\) for several \(p\).

# Eigenvalue clustering versus GMRES iteration counts (Problem 2.13)

For a (nonsymmetric / nonselfadjoint) preconditioned system with operator \(M^{-1}A\), the folklore
is that if \(M^{-1}A\) has \(m\) eigenvalue clusters then GMRES reaches an acceptable approximate
solution in \(O(m)\) steps. For non-normal matrices this can fail badly.

## Question

Find an interesting nonsymmetric model problem where the theoretical eigenvalue distribution of the
preconditioned matrix indeed corresponds to the actual GMRES convergence behaviour: \(M^{-1}A\) has
\(m\) eigenvalue clusters and GMRES obtains an acceptable approximate solution in \(O(m)\) steps.

## Target (two-sided)

(i) Construct small nonsymmetric examples where the \(m\)-clusters \(\Rightarrow O(m)\)-steps
correspondence holds, and (ii) construct small non-normal counterexamples where it fails (GMRES
takes \(\gg m\) steps despite \(m\) clusters), making the role of eigenvector conditioning explicit.

## Suggested experiments

Build block-diagonal / convection-diffusion-type matrices with a prescribed number of eigenvalue
clusters and a tunable non-normality (e.g. add large strictly-upper entries). Run GMRES, count the
steps to a fixed residual, and compare to the cluster count. Sweep non-normality to locate the
transition from "clustering predicts iterations" to "clustering misleads".

# When do Ritz values approximate eigenvalues of an invariant subspace? (Problem 3.4)

Let \(\hat V\) be an approximate invariant subspace of \(A\) of dimension \(d\), let \(W\) be another
subspace of dimension \(r<n-d\), and let \(Q\) be an orthonormal basis of \(\hat V + W\).

## Question

Provide conditions ensuring that \(d\) eigenvalues of \(Q^*AQ\) approximate the \(d\) eigenvalues of
\(A\) associated with the invariant subspace \(V\), under appropriate assumptions on the eigenvalues
of \(A\) corresponding to \(V\) (e.g. a spectral gap separating them from the rest).

## Target

Empirically characterize which assumptions (subspace angle \(\angle(\hat V,V)\), spectral gap,
\(\dim W\), conditioning) control the Ritz-value error, and identify when Rayleigh-Ritz succeeds or
fails. Produce a candidate sufficient condition supported by the data.

## Suggested experiments

Take small \(A\) with a known invariant subspace \(V\) and a spectral gap. Perturb \(V\) by a
controlled angle to get \(\hat V\), append a random \(W\), form \(Q\), compute the Ritz values of
\(Q^*AQ\), and measure the error to the target \(d\) eigenvalues as a function of angle, gap, and
\(\dim W\). Map the success/failure boundary.

# Deterministic diagonal perturbation giving an eigenvalue gap (Problem 3.2)

Let \(A\) be Hermitian tridiagonal. Minami's probabilistic result shows a random diagonal
perturbation with independent absolutely continuous entries opens an eigenvalue gap. The open
question asks for a DETERMINISTIC construction.

## Question

Give an efficient deterministic algorithm that, for Hermitian tridiagonal \(A\) and \(\delta>0\),
produces a diagonal \(E\) with \(\|E\|\le 1\) such that the perturbed matrix \(A+\delta E\) has
\(\operatorname{gap}(A+\delta E)\ge C(\delta/n)^c\), where \(\operatorname{gap}\) is the minimum
eigenvalue separation and \(C,c\) are universal constants.

## Target

Propose a simple deterministic diagonal pattern (e.g. \(E_{ii}=\cos(i\theta)\), an arithmetic ramp,
or a low-discrepancy sequence) and test empirically whether \(\operatorname{gap}(A+\delta E)\) meets
the \(C(\delta/n)^c\) form across \(n\) and \(\delta\); or exhibit a tridiagonal \(A\) defeating a
candidate construction.

## Suggested experiments

For Hermitian tridiagonal families (free Jacobi, discrete Laplacian, random tridiagonals) sweep
\(n\) and \(\delta\). For each candidate deterministic diagonal pattern, compute
\(\operatorname{gap}(A+\delta E)\) and fit it against \((\delta/n)^c\); record the smallest gap found
(worst case) and whether a fixed \((C,c)\) explains the data.
