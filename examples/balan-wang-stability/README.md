# Campaign: The Balan–Wang stability conjecture (phase retrieval at N = 2M−1)

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — universal constants for every $M$ and every
> full-spark frame; individual frames and Gaussian ensembles are internal tools. The
> driver designates the primary claim deterministically.
>
> Source: [Randomstrasse101](https://randomstrasse101.math.ethz.ch/posts/StablePhaseRetrieval/)
> (ETH Zürich open-problems blog), Conjecture 20, with Open Problem 21 and Conjecture 19
> as neighbors; archived as [arXiv:2603.29571](https://arxiv.org/abs/2603.29571).

## The problem

Real phase retrieval recovers $x$ from $|Ax|$ up to sign; $N = 2M-1$ measurements are the
minimum for injectivity, and stability there is governed by
$\omega(A) = \min \sigma_M(A_S)$ over row subsets whose complement fails to span
(Balan–Wang). Conjecture: for *every* full-spark $A \in \mathbb{R}^{(2M-1)\times M}$,
$\omega(A) \le C\max_k\lVert A_k\rVert\,\beta^M$ with universal $C$, $\beta < 1$ — stability
at the minimal measurement count is exponentially bad in the dimension, for every frame.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open** for general $A$. Decisive for the Gaussian case (the post's Open Problem 21):
Shmalo ([arXiv:2607.06249](https://arxiv.org/abs/2607.06249), Jul 2026) proves
$\frac1m\log\omega(A) \to -\log 4$ in probability for iid Gaussian
$A \in \mathbb{R}^{(2m-1)\times m}$ — Gaussian frames obey the conjectured form, and since
$\omega \le C R_m b^m$ fails whp for every $b < 1/4$, any universal $\beta$ must be $\ge 1/4$;
the worst-case-over-all-$A$ statement is untouched. Neighbor Conjecture 19 (complex
injectivity at $4M-5$): part (a) claimed in a June-2026 4-page "AI generated, human
verified" note (arXiv:2606.17922, unrefereed), part (b) open; "$4M-4$ necessary" is false
(Vinzant 2015), "generic $4M-4$ sufficient" is a theorem — see
[calibration-phase-retrieval](../calibration-phase-retrieval/).

## What this runs

`balan_wang_stability.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with numpy/scipy/sympy/mpmath → three audit-verified papers →
dossier → **driver-created primary claim** + `verdict --set-primary` →
`campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint → `problem verdict` → PDF.

Under full spark $\omega(A) = \min_{|S|=M}\sigma_M(A_S)$ — exactly computable for
$M \le 10$ (at most 92,378 subsets), and each value is certifiable for rational $A$ (exact
characteristic polynomials via `proof_submit`, sympy). The refutation side searches for
frames whose $\omega/\max\lVert A_k\rVert$ decays slower than exponentially (structured
harmonic/equiangular candidates, then optimization per $M$); the proof track calibrates the
tooling on the Gaussian $-\log 4$ law and tests structural lemmas on the instance zoo.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact $\omega$ tables and best-frame estimates $b_M$ for small $M$,
a numerical reproduction of the Gaussian scaling, and a status sketch that keeps the
theorem layer, the July 2026 Gaussian result (a preprint), and the open universal statement
apart — `COMPUTATIONAL_EVIDENCE`, not a resolution. A single frame proves nothing about
universal constants; only a proven family would refute.

## Selected references

- R. Balan, Y. Wang, *Invertibility and robustness of phaseless reconstruction*:
  [arXiv:1308.4718](https://arxiv.org/abs/1308.4718) (ACHA 2015).
- A. S. Bandeira, J. Cahill, D. G. Mixon, A. A. Nelson (2014), *Saving phase: injectivity
  and stability for phase retrieval*, ACHA 37.
- Y. Shmalo, *Extreme least singular values of Gaussian row submatrices and a phase
  retrieval stability problem*: [arXiv:2607.06249](https://arxiv.org/abs/2607.06249).
- A. Conca, D. Edidin, M. Hering, C. Vinzant (2015), *An algebraic characterization of
  injectivity in phase retrieval*, ACHA 38; C. Vinzant (2015), *A small frame and a
  certificate of its injectivity*, SampTA.
