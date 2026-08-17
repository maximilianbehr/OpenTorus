# Campaign: Real-rootedness of the Durfee polynomials

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every $n$; exact certificates for finitely
> many $n$ are internal tools. The driver designates the primary claim deterministically.
>
> Source: [AIM Problem List *Polyhedral geometry and partition theory*](http://aimpl.org/polypartition/1/)
> (ed. M. Olsen, AIM workshop Nov 2016; http only), Problem 1.2; origin
> Canfield–Corteel–Savage, *Durfee polynomials*, Electron. J. Combin. 5 (1998) #R32.

## The problem

Let $D(\lambda)$ be the side of the Durfee square of a partition $\lambda$ and
$D_n(x) = \sum_{\lambda \vdash n} x^{D(\lambda)}$. Does $D_n$ have only real roots for
every $n$? Its coefficients count partitions of $n$ by Durfee side, its degree is only
$\lfloor\sqrt n\rfloor$, and it is one of the cleanest partition statistics for which
real-rootedness is conjectured but unproved.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Canfield–Corteel–Savage (1998) verified real (negative) roots for $n \le 1000$
for ordinary partitions and seven related families, proved asymptotic log-concavity in
the central range $\varepsilon\sqrt n \le d \le (1-\varepsilon)\sqrt n$ plus
$|\text{mean} - \text{mode}| \le 1/2 + o(1)$, and stated the general question open; their
ninth family (Rogers–Ramanujan) has a non-real root at $n = 75$. Boyer–Goh
([arXiv:0711.1400](https://arxiv.org/abs/0711.1400)) restate the conjecture; the 2016 AIM
working group tried a coefficient recursion and a Brenti-transformation route with no
concrete result. Nothing since. Creation-time computation, done twice independently
(exact Sturm counts): real-rooted for every $n \le 800$, roots negative and simple,
minimal absolute root gap $\sim C/n^2$, minimal relative gap decaying slowly
(0.65 → 0.31 from $n = 100$ to $800$).

## What this runs

`durfee_real_roots.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with sympy/mpmath → four audit-verified papers (the journal-only
primary source is cited by DOI in the notes) → dossier → **driver-created primary claim**
+ `verdict --set-primary` → `prove --min-papers 4` → report + lint → `problem verdict` →
PDF.

The instance program is exact end to end: coefficients from the $q$-series DP, per-$n$
Sturm certificates via `proof_submit`, interlacing tests between consecutive
polynomials, and high-precision root tracking near the degree jumps $n = k^2$ where a
new root enters. One certified $n$ with a non-real pair would refute; a compatible-
polynomials / interlacing mechanism would be the proof route.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact certificates for a range of $n$, gap and interlacing statistics,
and a status sketch that keeps CCS's asymptotic theorems apart from the open all-$n$
statement — `COMPUTATIONAL_EVIDENCE`, not a resolution. Do not confuse $D_n$ with the
type-D Eulerian polynomial of the same name (that one is proved real-rooted).

## Selected references

- E. R. Canfield, S. Corteel, C. D. Savage, *Durfee polynomials*, Electron. J. Combin. 5
  (1998) #R32, DOI 10.37236/1370.
- R. P. Boyer, W. M. Y. Goh, *Polynomials associated with partitions: their asymptotics and
  zeros*: [arXiv:0711.1400](https://arxiv.org/abs/0711.1400).
- P. Brändén, *Unimodality, log-concavity, real-rootedness and beyond*:
  [arXiv:1410.6601](https://arxiv.org/abs/1410.6601).
- C. D. Savage, M. Visontai, *The s-Eulerian polynomials have only real roots*:
  [arXiv:1208.3831](https://arxiv.org/abs/1208.3831).
- S. B. Ekhad, D. Zeilberger, *A quick empirical reproof of the asymptotic normality of the
  Hirsch citation index*: [arXiv:1411.0002](https://arxiv.org/abs/1411.0002).
