**Simons workshop open problems (arXiv:2602.05394v3, 21 August 2026).** Thirteen
small-dimensional, numerically explorable open problems from "Linear Systems and Eigenvalue
Problems: Open Questions from a Simons Workshop" (47 numbered problems in the paper; these are
the ones probeable with matrix experiments at small dimension). Each `# ` heading below becomes
one dossier via `opentorus problem new --from-markdown notes.md --structured`; the first five
(dossiers PROBLEM-0001..0005) are the original set and keep their ids, the remaining eight
(PROBLEM-0006..0013) were extracted in a second pass. Two more workshop problems have
standalone examples: 4.6 (nystrom-submodularity) and 6.3 (matrix-sign-approximation).

**Read the v3 status updates first.** Version 3 of the preprint is "updated to reflect the
status of the open problems as of August 20, 2026" and adds twelve dated update blocks. Five of
the thirteen problems below are affected — 2.4, 2.20, 3.5, 4.2 and 4.3 — and each carries a
`## Status (paper v3, 20 August 2026)` section recording what is now claimed and what is left.
The other eight (2.13, 2.15, 2.17, 3.2, 3.4, 3.6, 3.8, 4.7) carry no update and stand as posed.
Problem 4.6, attacked by the standalone nystrom-submodularity example, is likewise claimed
resolved in v3; 6.3-6.5 (matrix-sign-approximation) are untouched.

The paper's own wording is "claims to solve" / "claims to give a negative answer" — these are
*claims recorded by the editors*, not verifications. Treat them the same way: a claimed
resolution is literature to reproduce and check, and it does not by itself set any claim in a
dossier to `verified`. Only a verification artifact does that. Before citing one of these
follow-up references in a report, add it locally (`opentorus paper add <url>`) — a
`REFERENCE_FACT` must cite a local source artifact, and missing metadata is marked missing
rather than invented. Note that `paper add` strips the version from an arXiv id, so it always
resolves the *current* version; the downloaded PDF is then SHA-256 pinned in the workspace.

**Machine-checkable pieces (all thirteen problems).** These are small-dimensional questions,
so most lemmas reduce to exact algebra at a fixed size — a characteristic polynomial factored
for a named matrix, a Ritz-value identity for a fixed $m$, an exact eigenvalue of a named
small example. Submit that core via `proof_submit(backend="sympy")`, or as an enclosure via
`proof_submit(backend="interval")` when the quantity is real but not rational. Only an
ACCEPTED `proof_submit` is machine-checked; `exp_run` results are evidence, not proof. Do NOT
manufacture a certificate for the general statement — record it as a `[GAP-n]` instead.

# Conditioning of Ritz values from random Krylov subspaces (Problem 3.5)

Let \(A\in\mathbb{C}^{n\times n}\) be arbitrary (not necessarily normal), let \(b\) be a random
starting vector, and let \(Q\in\mathbb{C}^{n\times m}\) have orthonormal columns spanning the
Krylov subspace \(K_m(A,b)=\operatorname{span}\{b,Ab,\dots,A^{m-1}b\}\). Form \(H=Q^*AQ\), whose
eigenvalues are the Ritz values of \(A\).

## Status (paper v3, 20 August 2026)

The v3 update block for Problem 3.5 records that

> Richard Peng, *A Diagonalizable Obstruction for Random Two-Step Ritz Compressions*, 2026.
> <https://yangpliu.github.io/repo/two-step-ritz-obstruction/paper.pdf>

**claims negative answers to both questions as stated**: for every even \(n\) it constructs a
real diagonalizable \(A_n\), uniformly bounded in norm, such that for a standard real Gaussian
start \(b\) and \(k=2\),
\(\Pr[\kappa_V(Q^\top A_nQ)\ge e^n/5]\ge 1-2e^{-n/40}\) — exponential, not polynomial.

So the working hypothesis below is the one now claimed to be false. The dossier's job is to
*check the claim*, not to inherit it: reproduce the construction numerically at \(k=2\), see
whether the stated probability bound is visible at reachable \(n\), and probe what survives
outside the claimed regime (\(k>2\), other start distributions, complex \(A\)). Record the
claimed obstruction as literature; do not set the problem to resolved without a verification
artifact.

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

## Status (paper v3, 20 August 2026)

The v3 update block for Problem 2.4 records that

> Leheng Chen, Zihao Liu, Wanyi He and Bin Dong, *Iteris: Agentic Research Loops for
> Computational Mathematics*, [arXiv:2606.02484](https://arxiv.org/abs/2606.02484), 2026

**claims to solve** Problem 2.4. The editors add that 2.4 is a stylized question, and that the
much broader motivating question — characterizing when sketch-and-project beats CG for general
spectra, right-hand sides, preconditioning and finite precision — **remains open**.

Retarget accordingly: the stylized \(\lambda_i=i^{-p}\) sweep below is now a *check* on a
claimed answer (does the measured ratio match what the reference predicts, and where does it
break?), while the open deliverable is the broader comparison. Reproducing a claimed result and
finding it holds is evidence, not verification.

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

# The Forsythe conjecture for restarted CG (Problem 2.20)

Apply CG to \(f(x)=\tfrac12 x^TAx - x^Tb\) with SPD \(A\), restarted every \(s\) steps: from
\(x_k\) take \(x_{k+1}\in x_k+\mathcal{K}_s(A,y_k)\) with \(x_\star-x_{k+1}\perp_A \mathcal{K}_s(A,y_k)\),
where \(y_k=r_k/\lVert r_k\rVert\) is the normalized residual. Forsythe's conjecture: for
\(2\le s< d(A)\) (degree of the minimal polynomial, with \(d(A,r_0)\ge s+1\)), each of the two
subsequences \(\{y_{2k}\}\) and \(\{y_{2k+1}\}\) has a single limit vector.

## Status (paper v3, 20 August 2026)

The v3 update block for Problem 2.20 records three references that **claim to have solved it for
\(s=2\)**:

> Matthew J. Colbrook, George Stepaniants and Alex Townsend, *A Proof of the Forsythe Conjecture
> for the Two-Step Restarted Conjugate Gradient Method*,
> [arXiv:2608.02852](https://arxiv.org/abs/2608.02852), 2026
>
> Jarek Liesen, *Proof of the Forsythe Conjecture for s = 2*, 2026.
> <https://jarek.ai/papers/proof-of-the-forsythe-conjecture-for-s-2.pdf>
>
> Richard Peng, *Convergence of Normalized Residuals for Restarted Conjugate Gradients of Length
> Two*, 2026. <https://yangpliu.github.io/repo/restarted-cg-two/paper.pdf>

\(s=1\) was already known (steepest descent), so the open range is now \(s\ge 3\). Point the
counterexample search there and keep \(s=2\) only as a sanity check: a run at \(s=2\) that
looked like two accumulation points would contradict three independent claimed proofs and is far
more likely a precision artifact — re-verify at higher precision before recording anything.

## Question

Do the even and odd normalized-residual subsequences of \(s\)-step restarted CG each converge
to a single limit vector, for every SPD \(A\) and every \(s\ge 2\)?

## Working hypothesis to test

Known: proved for \(s=1\) (steepest descent); \(\lim_k\lVert y_{2k+2}-y_{2k}\rVert=0\) holds in
general but does not imply convergence of the subsequence. Numerical evidence in the
literature suggests the conjecture is true; a sequence with several accumulation points
would refute it.

## Suggested experiments

WLOG \(A\) diagonal (orthogonal invariance): small \(n\) (6–30), adversarial spectra
(equispaced, geometric, clustered pairs, Chebyshev points), several \(s\). The differences
decay geometrically, so run the recurrence in mpmath (200+ digits) as well as float64:
track \(\lVert y_{2k+2}-y_{2k}\rVert\), Cauchy-ness of both subsequences, and angles to
candidate limit vectors; search over random \(x_0\) and spectra (optimization) for slow or
oscillating cases — any run whose even subsequence visits two well-separated accumulation
points repeatedly is a counterexample candidate to re-verify at higher precision.

# Updated CG residuals below machine precision (Problem 2.15)

CG and steepest descent update \(x_k=x_{k-1}+a_{k-1}p_{k-1}\) and
\(r_k=r_{k-1}-a_{k-1}Ap_{k-1}\); in floating point the updated \(r_k\) is not the true
residual \(b-Ax_k\). Analyses of the attainable accuracy assume — but do not prove — that
the updated residual norms shrink well below machine precision.

## Question

Determine conditions on \(A\) that ensure the updated residual norms \(\lVert r_k\rVert\) drop
below machine precision in finite-precision arithmetic — or exhibit examples where they
do not.

## Target (two-sided)

(i) Empirical sufficient conditions (spectrum shape, conditioning) under which the floor
\(\min_k\lVert r_k\rVert\) reliably falls below unit roundoff; (ii) explicit SPD matrices
where the updated residual stagnates above machine precision — an exactly checkable,
counterexample-shaped deliverable.

## Suggested experiments

Textbook CG and steepest descent in float32 and float64, small \(n\) (20–100), thousands of
iterations past stagnation: geometric spectra with \(\kappa\) up to \(10^{16}\), clustered
spectra with tiny outliers, random Wishart. Record updated vs true residual norms and the
floor \(\min_k\lVert r_k\rVert/u\); then maximize that floor over spectra/eigenvector coupling
with black-box optimization. Cross-check float32 candidates in float64 to separate genuine
structure from precision artifacts.

# Precision needed for n-step CG convergence (Problem 2.17)

In exact arithmetic CG terminates in \(n\) steps; in finite precision, loss of orthogonality
delays convergence, and existing analyses demand precision far above the ideal
\(\log(1/\epsilon)+c\log n\) bits.

## Question

How many bits of precision are necessary to guarantee that CG applied to an \(n\times n\) SPD
system \(Ax=b\) obtains an approximate solution with normwise backward error at most
\(\epsilon\) in \(n\) (or fewer) steps?

## Target

An empirical scaling law for the minimal mantissa length \(p(n,\kappa,\epsilon)\): does it
grow like \(\log\kappa+\log n+\log(1/\epsilon)\), or does some spectrum family force much more?
Identify the worst spectra.

## Suggested experiments

Implement CG with adjustable mantissa (mpmath, \(p=10\dots200\) bits). For each
\((n,\text{spectrum},\epsilon)\), bisect on \(p\) for the property "normwise backward error
\(\le\epsilon\) within \(n\) steps"; use spectra known to break Lanczos orthogonality (tight
clusters plus outliers, Strakoš matrices); \(n=10\dots100\) suffices since the phenomenon is
spectral. Fit \(p\) against \(\log\kappa\), \(n\), and \(\log(1/\epsilon)\).

# Distribution of Ritz values across the numerical range (Problem 3.6)

For non-Hermitian \(A\) and \(Q\in\mathbb{C}^{n\times k}\) with orthonormal columns, the Ritz
values (eigenvalues of \(Q^*AQ\)) lie in the numerical range \(W(A)\). The Hermitian case is
answered by Cauchy interlacing; \(k=1\) and \(k=n\) are understood, and \(k=n-1\) is known for
normal \(A\).

## Question

What can be said — deterministically or probabilistically — about the distribution of the
Ritz values across \(W(A)\) for \(1<k<n\)? What changes when \(Q\) is restricted to a Krylov
basis, or drawn as a random subspace?

## Target

Empirical laws: the density of Ritz values relative to \(W(A)\) (boundary vs interior mass)
as a function of \(k/n\) and non-normality, for Haar-random vs Krylov \(Q\); plus small-scale
attainability tests (which prescribed Ritz configurations are reachable by some \(Q\)) to
seed conjectures.

## Suggested experiments

\(n=8\dots50\); \(A\in\{\)Jordan block, Grcar, Ginibre, perturbed circulant shift, normal with
prescribed spectrum\(\}\). Sample Haar \(Q\) (QR of Ginibre) and Krylov \(Q\) with random start;
compute Ritz values; estimate the boundary of \(W(A)\) via eigenvalues of the Hermitian part
of \(e^{i\theta}A\) and record the distance-to-boundary distribution. For tiny \(n,k\), attempt
prescribed target configurations by optimization over the Stiefel manifold. (Reuses the
Arnoldi tooling of the Problem 3.5 dossier.)

# An O(kn) bidiagonal SVD in the MR3 family (Problem 3.8)

For upper bidiagonal \(B\in\mathbb{R}^{n\times n}\), one wants \(k\) singular triples
\((\sigma_i,u_i,v_i)\) in \(O(kn)\) time with coupling residual
\(\lVert Bv_i-\sigma_i u_i\rVert_2=O(\epsilon n\lVert B\rVert_2)\) and orthogonality
\(|v_i^Hv_j|,|u_i^Hu_j|=O(\epsilon n)\). MR3 applied to \(B^HB\) and \(BB^H\) separately loses
the coupling; the Golub–Kahan form often loses orthogonality; two implementations were
ultimately ruled unreliable for LAPACK.

## Question

Is there an \(O(kn)\) bidiagonal SVD with both guarantees — and are the known failures of
the MR3-based attempts a bug or a genuine gap in the theory?

## Target

A failure-mode map: which singular-value distributions (glued clusters, relative-gap
patterns) break which route (\(B^HB\), \(BB^H\), Golub–Kahan), measured by the residual and
orthogonality criteria above — extracting the features of problematic bidiagonals that a
repaired algorithm or theory would have to handle.

## Suggested experiments

Small \(n\) (50–500) bidiagonals: glued clusters, geometric decay, Wilkinson-glued patterns.
Compute singular triples via the three routes (LAPACK MRRR through
`scipy.linalg.eigh_tridiagonal(driver='stemr')` on the associated tridiagonals, plus the
Golub–Kahan permuted form); measure coupling residuals and orthogonality against cluster
gap and relative-gap statistics; map the empirical failure boundary.

# GECP on the fermionic kernel (Problem 4.2)

The discrete Lehmann representation of imaginary-time Green's functions rests on low-rank
approximation of \(K(t,\omega)=e^{-t\omega}/(1+e^{-\omega})\) on
\([0,1]\times[-\Lambda,\Lambda]\). Gaussian elimination with complete pivoting (greedy cross
approximation) provably reaches \(\varepsilon\) at rank \(k=O(\Lambda+\log(1/\varepsilon))\),
but a rank-\(k\) approximation with \(k=O(\log\Lambda\,\log(1/\varepsilon))\) exists — and
empirically GECP tracks the better rate. Applications run \(\Lambda=10^5\)–\(10^6\), so the
gap matters.

## Status (paper v3, 20 August 2026)

The v3 update block for Problem 4.2 records that

> Venkata Siddharth Pendyala, *Local-to-Global Convergence of Greedy Cross Approximation for
> Totally Positive Kernels*, 2026. <https://doi.org/10.5281/zenodo.21863274>

**claims to have solved** it: GECP on the continuous fermionic kernel satisfies
\(k=O(\log(\Lambda)\log(1/\varepsilon))\Rightarrow\lVert K-\hat K\rVert_\infty\le\varepsilon\),
attaining (up to universal constants) the rank scaling previously known only for *existence* of a
low-rank approximation — and the same bound holds for any finite matrix obtained by sampling
\(K\) at distinct time and frequency nodes. Related progress is credited to

> Marc Aurèle Gilles, *Convergence rates for pivoted QR and LU*,
> [arXiv:2607.26863](https://arxiv.org/abs/2607.26863), 2026.

The empirical law \(k(\varepsilon,\Lambda)\) below is therefore no longer a search between two
candidate rates: the better rate is the claimed theorem, and the experiment is a check on it plus
a measurement of the constants and pivot structure it does not pin down.

## Question

Prove stronger theoretical bounds for GECP applied to \(K\), exploiting the structure of the
kernel.

## Target

A precise empirical law \(k(\varepsilon,\Lambda)\) for GECP on \(K\), fitted against both
candidate rates across decades of \(\Lambda\), plus structural observations that could seed a
proof: where the pivots land (near-log-uniform in \(\omega\)?), how cross-matrix volumes
grow, connections to sum-of-exponentials approximation.

## Suggested experiments

Discretize \(K\) on fine grids (Chebyshev in \(t\), log-symmetric in \(\omega\); overflow-safe
evaluation), \(\Lambda\in\{10,10^2,\dots,10^5\}\); run greedy complete-pivoted cross
approximation; record sup-norm error vs \(k\); fit against \(O(\Lambda+\log 1/\varepsilon)\) and
\(O(\log\Lambda\log 1/\varepsilon)\); log pivot locations and analyze their distribution.
(The gecp-growth-factor example probes GECP's growth factor in general; here the question
is the approximation rate on one structured kernel.)

# Row selection by QRCP on orthonormal columns (Problem 4.3)

For \(Q\in\mathbb{R}^{n\times k}\) with orthonormal columns there is always a row subset
\(\mathcal{I}\) with \(\lVert Q(\mathcal{I},:)^{-1}\rVert_2\le\sqrt{k(n-k+1)}\), computable in
\(O(nk^2)\). Practical column-pivoted QR (QRCP) has exponential-in-\(k\) worst-case bounds —
but the known worst cases do not have orthonormal columns.

## Status (paper v3, 20 August 2026)

The v3 update block for Problem 4.3 records that Theorem 2 of

> Leheng Chen, Zihao Liu, Wanyi He and Bin Dong, *Iteris: Agentic Research Loops for
> Computational Mathematics*, [arXiv:2606.02484](https://arxiv.org/abs/2606.02484), 2026

**claims a negative answer**: it constructs a family of \(Q\) showing that no bound of the form
\(\lVert Q(\mathcal{I},:)^{-1}\rVert_2\le Ck^\alpha\sqrt{k(n-k+1)}\) can hold for any constant
\(C\) and exponent \(\alpha>0\). On the positive side,

> Anil Damle, *Computing Strong Rank-Revealing Factorizations for Matrices with Orthonormal
> Rows*, [arXiv:2607.13532](https://arxiv.org/abs/2607.13532), 2026

shows that replacing Golub-Businger pivoting by Bischof-Stewart pivoting yields
\(\lVert Q(\mathcal{I},:)^{-1}\rVert_2\le\sqrt{k(n-k)+1}\).

So the adversarial Stiefel search below is now aimed at a claimed-known target: reproduce the
claimed family for the QRCP actually used in practice (`scipy.linalg.qr(..., pivoting=True)` is
Golub-Businger), and measure Bischof-Stewart on the same inputs to see the claimed separation.
The two pivoting rules disagreeing on the same \(Q\) is the checkable signal.

## Question

Does the QRCP algorithm used in practice satisfy the \(\sqrt{k(n-k+1)}\) bound, or a similar
polynomial bound, on orthonormal-column inputs?

## Working hypothesis to test

Prove-or-disprove shaped: either QRCP-selected rows keep
\(\lVert Q(\mathcal{I},:)^{-1}\rVert_2\) polynomially bounded on orthonormal inputs, or some
orthonormal family drives it super-polynomially — a counterexample is a single explicit
matrix, exactly checkable.

## Suggested experiments

\(\mathcal{I}\) = first \(k\) pivots of `scipy.linalg.qr(Q.T, pivoting=True)`; measure
\(\rho(Q)=\lVert Q(\mathcal{I},:)^{-1}\rVert_2/\sqrt{k(n-k+1)}\) for (i) Haar-random \(Q\)
across \((n,k)\), (ii) structured \(Q\) (orthonormal factors of Kahan matrices, eigenvector
blocks of graph Laplacians, subsampled DFT/Hadamard columns), (iii) adversarial
maximization of \(\rho\) over the Stiefel manifold at small \(n\) (\(\le 60\)), tracking the
growth of the maximized \(\rho\) with \(k\).

# Volume sampling versus optimal column subset selection (Problem 4.7)

For a positive vector \(\lambda\), let
\(x_k(\lambda)=\max_{V\in SO(n)}\min_{|\mathcal{I}|=k}\operatorname{Tr}[K-K_{:,\mathcal{I}}K_{\mathcal{I},\mathcal{I}}^{-1}K_{\mathcal{I},:}]\)
with \(K=V^\top\operatorname{diag}(\lambda)V\) — the worst case over rotations of the optimal
subset trace error — and let \(y_k(\lambda)=(k+1)\,e_{k+1}(\lambda)/e_k(\lambda)\) be the
volume-sampling value (elementary symmetric polynomials). For \(k=n-1\) the two are equal.

## Question

Prove a tightness bound between \(x_k(\lambda)\) and \(y_k(\lambda)\) for general \(k\); limited
empirical investigation indicates the two are usually quite close.

## Target

The empirical worst-case ratio \(x_k/y_k\) over \((n,k)\) and \(\lambda\)-profiles, the
structure of the extremal rotations \(V\), and either a conjectured universal bound or a
\(\lambda\) pushing the ratio far from 1.

## Suggested experiments

\(n=4\dots8\), \(k=1\dots n-1\): \(y_k\) exactly via symmetric polynomials (sympy);
\(x_k\) by maximizing over \(V\) (exponential map of skew-symmetric matrices, multi-start
`scipy.optimize`), inner minimum by brute force over all \(\binom{n}{k}\) subsets. Scan
\(\lambda\) families (geometric, flat-plus-outliers, two-cluster, \(1/i\)); tabulate the
maximal ratio and the extremal structure; validate the \(k=n-1\) identity as a correctness
check.
