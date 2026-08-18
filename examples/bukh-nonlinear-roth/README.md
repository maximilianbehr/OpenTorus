# Campaign: Bukh's nonlinear Roth pattern $x,\ y,\ y + P(x) - P(y)$

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified statement — every nonlinear $P$, every large prime, every
> dense set; exact small-$p$ extremal sets are internal tools. The driver designates the
> primary claim deterministically.
>
> Source: [AIM Problem List *High-dimensional phenomena in discrete analysis*](http://aimpl.org/highdimdiscrete/2/)
> (ed. J. Lim, AIM workshop May 2024, org. Conlon–Peluse–Zhao; http only), Problem 2.1
> [Boris Bukh].

## The problem

For a nonlinear polynomial $P$ and $A \subseteq \mathbb{F}_p$ with $|A| > p^{0.99}$, must
there be distinct $x, y \in A$ with $y + P(x) - P(y) \in A$? For $P(x) = 2x$ this is
Roth's theorem on three-term progressions. For any nonlinear $P$ nothing is known: the
"common difference" $P(x) - P(y)$ depends on the base point, so the pattern is not
translation-invariant and falls outside the Peluse-type progressions
$x,\ x + P_1(y),\ x + P_2(y)$ for which power-saving bounds exist.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** No result, preprint, or claim treats the pattern for any nonlinear $P$. The
related polynomial-progression theorems (Bourgain–Chang
[arXiv:1608.05448](https://arxiv.org/abs/1608.05448), Peluse
[arXiv:1707.05977](https://arxiv.org/abs/1707.05977), Dong–Li–Sawin
[arXiv:1709.00080](https://arxiv.org/abs/1709.00080), Peluse
[arXiv:1909.00309](https://arxiv.org/abs/1909.00309), and the 2024–2026 follow-ups) are
labelled *related*, not special cases. Creation-time computation, done twice
independently (exact SAT, brute-force cross-checked): the maximum pattern-free set for
$P = x^2$ has size $11$ at $p = 59$ (against $p^{0.99} = 56.6$), growing like
$\approx p^{0.6}$–$p^{0.65}$ over $p \le 59$; the trivial pairing bound gives
$\le (p+1)/2$ for $P = x^2$, and the interval $[a, 2a]$ with $a \approx \sqrt{p/2}$ is
pattern-free.

## What this runs

`bukh_nonlinear_roth.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with python-sat + sympy → four audit-verified papers →
dossier → **driver-created primary claim** + `verdict --set-primary` →
`campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint → `problem verdict` → PDF.

The instance program is exact end to end: forbidden pairs/triples in $\mathbb{F}_p$,
maximum pattern-free sets by SAT with cardinality bisection, explicit extremal sets and
the pairing bound via `proof_submit`, growth-exponent fits across several $P$. A
construction beating $p^{0.99}$ for all large $p$ would refute; controlling the counting
operator $\mathbb{E}_{x,y} f(x)f(y)f(y + P(x) - P(y))$ is the proof route, and the notes
say where the standard tools stop.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact small-$p$ extremal data, a clear statement of why the pattern is
not a Peluse-type progression, and a status sketch — `COMPUTATIONAL_EVIDENCE`, not a
resolution. Do not quote the $p^{-1/15}$, $p^{-1/24}$, $p^{-1/12}$ bounds as if they
applied here.

## Selected references

- S. Peluse, *Three-term polynomial progressions in subsets of finite fields*:
  [arXiv:1707.05977](https://arxiv.org/abs/1707.05977) (Israel J. Math. 2018).
- D. Dong, X. Li, W. Sawin, *Improved estimates for polynomial Roth type theorems in finite
  fields*: [arXiv:1709.00080](https://arxiv.org/abs/1709.00080).
- J. Bourgain, M.-C. Chang, *Nonlinear Roth type theorems in finite fields*:
  [arXiv:1608.05448](https://arxiv.org/abs/1608.05448).
- S. Peluse, *Bounds for sets with no polynomial progressions*:
  [arXiv:1909.00309](https://arxiv.org/abs/1909.00309) (Forum Math. Pi 2020).
