# Campaign: The Lovász number of random circulant graphs

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full asymptotic conjecture — $\mathbb E\vartheta = (1+o(1))\sqrt n$ for every
> $n$ along the random circulant model; individual graphs and Monte Carlo curves are internal
> tools. The driver designates the primary claim deterministically.
>
> Source: [Randomstrasse101](https://randomstrasse101.math.ethz.ch/posts/lovasz-circulant/)
> (ETH Zürich open-problems blog), Conjecture 18, with Conjecture 17 ($G(n,1/2)$) as sibling;
> archived as [arXiv:2603.29571](https://arxiv.org/abs/2603.29571).

## The problem

The Lovász theta function of a random graph sits between the clique and chromatic numbers
and is the canonical SDP relaxation; for $G(n,1/2)$ it is known to be $\Theta(\sqrt n)$ with
the constant open for 40 years. For a *random circulant graph* (Cayley graph of
$\mathbb{Z}/n$ with random chord set) $\vartheta$ collapses to a linear program, and
$\vartheta(G)\vartheta(\overline G) = n$ exactly — so the conjecture $\mathbb E\vartheta = (1+o(1))\sqrt n$
says the theta function concentrates at the geometric mean of its trivial bounds.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Rigorous: $\sqrt n \le \mathbb E\vartheta \le C\sqrt{n\log\log n}$
(Bandeira–Błasiok–Dmitriev–Faure–Kireeva–Kunisky,
[arXiv:2502.16227](https://arxiv.org/abs/2502.16227); LP formulation from
Magsino–Mixon–Parshall, [arXiv:1907.05971](https://arxiv.org/abs/1907.05971); the RIP step
provably cannot remove the $\log\log$). Sibling Conjecture 17 for $G(n,1/2)$: open;
$\sqrt n \le \mathbb E\vartheta \le 2\sqrt n$ (Lovász 1979 + symmetry; Juhász 1982) unchanged
for 40+ years; Feige–Grinberg ([arXiv:2506.02952](https://arxiv.org/abs/2506.02952)) give new
poly-time upper bounds and a competing *heuristic* conjecture $\mathbb E\vartheta < 1.55\sqrt n$.
Paley graphs are the deterministic analogue ([paley-clique](../paley-clique/)).

## What this runs

`lovasz_theta_random.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with scipy/sympy/cvxpy → three audit-verified papers → dossier →
**driver-created primary claim** + `verdict --set-primary` → `prove --min-papers 3` →
report + lint → `problem verdict` → PDF.

The instance program is fast and exact where it matters: the frequency-domain LP solves
$\vartheta$ of a circulant graph in milliseconds up to $n \sim 10^4$, and any single
instance gets a rational primal–dual certificate via `proof_submit`; Monte Carlo curves of
$\mathbb E\vartheta/\sqrt n$, exhaustive enumeration of all circulants for $n \le 25$,
extremal-chord-set mining, and an SDP comparison for $G(n,1/2)$. The refuting direction
needs a structured family with provably large $\vartheta$; the proving direction is
asymptotic — both beyond any computation.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: certified per-instance $\vartheta$ values, ratio curves with confidence
intervals, extremal statistics, and a status sketch that keeps the theorem
($\sqrt{n\log\log n}$), the two open conjectures, and the heuristic $1.55$ apart —
`NUMERICAL_EVIDENCE` / `COMPUTATIONAL_EVIDENCE`, not a resolution. Curves at $n \le 10^4$
cannot distinguish $1$ from $1+\varepsilon$ from $\sqrt{\log\log n}$ growth; the dossier says so.

## Selected references

- L. Lovász (1979), *On the Shannon capacity of a graph*, IEEE Trans. IT 25.
- F. Juhász (1982), *The asymptotic behaviour of Lovász' ϑ function for random graphs*,
  Combinatorica 2; A. Coja-Oghlan (2005), CPC 14.
- Bandeira–Błasiok–Dmitriev–Faure–Kireeva–Kunisky, *The Lovász number of random circulant
  graphs*: [arXiv:2502.16227](https://arxiv.org/abs/2502.16227).
- U. Feige, V. Grinberg, *Upper bounds on the theta function of random graphs*:
  [arXiv:2506.02952](https://arxiv.org/abs/2506.02952).
- M. Magsino, D. G. Mixon, H. Parshall: [arXiv:1907.05971](https://arxiv.org/abs/1907.05971).
