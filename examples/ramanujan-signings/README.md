# Campaign: Random signings of Ramanujan graphs

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified statement — constant success probability for every
> Ramanujan base of every fixed degree; individual graphs and Monte Carlo families are
> internal tools. The driver designates the primary claim deterministically.
>
> Source: [AIM Problem List *Connecting communities via the block model*](http://aimpl.org/blockmodel/5/)
> (ed. A. Wein, AIM workshop May 2017; the site serves http only), Section 5 "Random
> matrix theory", Problem 5.3 (N. Srivastava).

## The problem

Sign the edges of a $d$-regular Ramanujan graph uniformly at random. Is the signed
adjacency matrix $S$ nearly Ramanujan — $\lVert S\rVert < 2\sqrt{d-1}+\varepsilon$ — with
probability bounded away from zero? Equivalently: is a random 2-lift of a Ramanujan graph
nearly Ramanujan with constant probability? (Bilu–Linial's conjecture asks for *some* good
signing; Marcus–Spielman–Srivastava proved a one-sided one always exists.)

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Partially resolved, open in general.** Mohanty–O'Donnell–Paredes
([arXiv:1909.06988](https://arxiv.org/abs/1909.06988), STOC 2020): for any $d$-regular
graph that is bicycle-free at radius $r \gg (\log\log n)^2$, a random signing has
$\rho(S) \le 2\sqrt{d-1}(1+o(1))$ whp — a YES for large-girth Ramanujan families (LPS,
Morgenstern) and random regular graphs. **Open:** Ramanujan bases with many short cycles.
Background: Bilu–Linial ([arXiv:math/0312022](https://arxiv.org/abs/math/0312022)),
MSS ([arXiv:1304.4132](https://arxiv.org/abs/1304.4132), one-sided existence),
Agarwal–Chandrasekaran–Kolla–Madan ([arXiv:1311.3268](https://arxiv.org/abs/1311.3268),
$\lambda + O(\sqrt d)$ whp), Bandeira–van Handel (large $d$). A June-2026
interlacing-families preprint claiming $2\sqrt{3(d-1)}$ was withdrawn on 2026-07-09 with
the note that stronger results already exist. Exact creation-time computation over all
signings of small Ramanujan graphs (Petersen .97, Heawood .91, Coxeter .91, $K_4$ .75, …;
independently re-run) sits in the dossier as a reproduction target.

## What this runs

`ramanujan_signings.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with numpy/scipy/sympy/networkx → four audit-verified papers → dossier
→ **driver-created primary claim** + `verdict --set-primary` → `prove --min-papers 5` →
report + lint → `problem verdict` → PDF.

The instance program is exact for small graphs — enumerate all signings modulo switching
($2^{m-n+1}$ classes) and certify each spectral radius by integer characteristic
polynomials via `proof_submit` — and Monte Carlo for LPS graphs versus short-cycle-rich
Ramanujan graphs of the same degree, exactly the regime MOP leaves open. The refuting
direction needs a Ramanujan family with dense short cycles and vanishing success
probability (with proof); the proving direction needs the trace method to survive short
cycles.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact signing statistics for named Ramanujan graphs, Monte Carlo
excess distributions across families, and a status sketch that keeps the theorem (MOP,
with its bicycle-free hypothesis stated every time), the one-sided existence result, and
the open short-cycle case apart — `COMPUTATIONAL_EVIDENCE`, not a resolution. Do not cite
the withdrawn deterministic-signing preprint.

## Selected references

- Y. Bilu, N. Linial (2006), *Lifts, discrepancy and nearly optimal spectral gap*,
  Combinatorica 26: [arXiv:math/0312022](https://arxiv.org/abs/math/0312022).
- A. Marcus, D. Spielman, N. Srivastava (2015), *Interlacing families I*, Ann. Math. 182:
  [arXiv:1304.4132](https://arxiv.org/abs/1304.4132).
- N. Agarwal, K. Chandrasekaran, A. Kolla, V. Madan: [arXiv:1311.3268](https://arxiv.org/abs/1311.3268).
- S. Mohanty, R. O'Donnell, P. Paredes, *Explicit near-Ramanujan graphs of every degree*:
  [arXiv:1909.06988](https://arxiv.org/abs/1909.06988) (STOC 2020).
- A. S. Bandeira, R. van Handel, arXiv:1408.6185; J. Huang, T. McKenzie, H.-T. Yau,
  arXiv:2412.20263.
