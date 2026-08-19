# Campaign: Fisk's 3×3 Toeplitz-minor conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every real-rooted polynomial with positive
> coefficients, every degree; individual polynomials and small-degree discriminant proofs
> are internal tools. The driver designates the primary claim deterministically.
>
> Source: [AIM Problem List *Theory and applications of total positivity*](http://aimpl.org/totalpos/1/)
> (workshop July 2023), Problem 1.6 = [*Stability, hyperbolicity, and zero localization*](http://aimpl.org/hyperbolicpoly/3/)
> (2011), Conjecture 3.2; original: S. Fisk, arXiv:0808.1850.

## The problem

Take a real-rooted polynomial with positive coefficients $a_k$ and replace each
coefficient by the $3\times3$ Toeplitz minor centred on it. Is the result still
real-rooted? Brändén proved the $2\times2$ version (a Turán-type transform); Fisk asked
about $3\times3$ and beyond. Via Jacobi–Trudi the coefficients are rectangular Schur
polynomials in the roots — a bridge between real-rootedness and total positivity.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open** for $3\times3$ and all $m \ge 3$. Brändén ([arXiv:0909.1927](https://arxiv.org/abs/0909.1927),
Crelle 2011): $m = 2$. Yoshida ([arXiv:1005.4218](https://arxiv.org/abs/1005.4218)):
$T_m[(1+x)^n]$ real-rooted for all $m, n$; the *adjacent* Fisk question
$a_k^2 - a_{k-r}a_{k+r}$ holds for $r \le 4$ but **fails at $r = 6$** (through a
transcendental example; $r = 5$, $r \ge 7$ open) — Fisk-type questions can be false. The
July 2023 AIM workshop report records the approaches tried by its working group. Creation-time computation: ~1350 random real-rooted polynomials of degree
4–12 through $T_3$ (and hundreds through $T_4, T_5, T_6$), exact Sturm checks, no failure;
a symbolic discriminant argument proves the $3\times3$ case for degree $\le 4$.

## What this runs

`fisk_toeplitz_minors.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with sympy/mpmath/scipy → three audit-verified papers →
dossier → **driver-created primary claim** + `verdict --set-primary` →
`campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint → `problem verdict` → PDF.

The instance program is exact: $T_3[p]$ over rationals, real-rootedness by Sturm
sequences, random and adversarial root vectors across scales (the $r = 6$ failure suggests
irregular coefficient patterns), and small-degree discriminant certificates in the roots
(degree $\le 4$ proved; degree 5 explored) — each via `proof_submit`. One exact
non-real-rooted output would refute; the proof track asks why Brändén's operator theory
does not lift to a transform cubic in the coefficients.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: certified small-degree theorems (degree $\le 4$), large random
searches with exact certificates on flagged instances, minimal-root-gap landscapes, and a
status sketch keeping Brändén's $2\times2$ theorem, Yoshida's partial results, and the
open $3\times3$ statement apart — `COMPUTATIONAL_EVIDENCE` plus a
`VERIFIED_PARTIAL_THEOREM`-grade artifact for degree $\le 4$, not a resolution.

## Selected references

- S. Fisk, *Questions about determinants and polynomials*: [arXiv:0808.1850](https://arxiv.org/abs/0808.1850).
- P. Brändén, *Iterated sequences and the geometry of zeros*: [arXiv:0909.1927](https://arxiv.org/abs/0909.1927)
  (J. reine angew. Math. 658, 2011).
- R. Yoshida, *On some questions of Fisk and Brändén*: [arXiv:1005.4218](https://arxiv.org/abs/1005.4218)
  (Complex Var. Elliptic Equ. 2013).
