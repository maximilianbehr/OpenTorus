# Campaign: The Kannan–Lovász–Simonovits (KLS) conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — a universal Cheeger/Poincaré constant for
> every isotropic log-concave measure in every dimension; individual bodies are internal
> tools. The driver designates the primary claim deterministically.
>
> Source: [Randomstrasse101](https://randomstrasse101.math.ethz.ch/posts/KLSConjecture/)
> (ETH Zürich open-problems blog), Conjecture 30; archived as
> [arXiv:2603.29571](https://arxiv.org/abs/2603.29571).

## The problem

Among all ways to cut a convex body (or log-concave measure) into two pieces, are
hyperplane cuts within a constant factor of the worst? KLS (1995) says yes, uniformly in
the dimension — the central open question of high-dimensional convex geometry, equivalent
to a dimension-free Poincaré inequality, and the reason ball-walk sampling should mix in
$\tilde O(n^2)$ steps.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open**, in a rapidly moving neighborhood. Best established lower bound on the KLS
constant: $\psi_n \ge c(\log n)^{-1/2}$ (Klartag 2023,
[arXiv:2303.14938](https://arxiv.org/abs/2303.14938)), after $n^{-1/2}$ (KLS),
$n^{-1/3}$ (Eldan), $n^{-1/4}$ (Lee–Vempala, survey [arXiv:1807.03465](https://arxiv.org/abs/1807.03465)),
$\exp(-\sqrt{\log n\log\log n})$ (Chen). Two consequences are now **theorems with
universal constants**: Bourgain's slicing problem (Klartag–Lehec,
[arXiv:2412.15044](https://arxiv.org/abs/2412.15044), Dec 2024, via Guan; independently
Bizeul) and the thin shell conjecture (Klartag–Lehec,
[arXiv:2507.15495](https://arxiv.org/abs/2507.15495)); Eldan 2013 turns thin shell into KLS
up to $\log n$ (up to $\sqrt{\log n}$ with a third-moment-tensor bound). **Claimed** (July
2026, two concurrent AI-assisted preprints — Chen–Klartag,
[arXiv:2607.23307](https://arxiv.org/abs/2607.23307), "proof found by GPT-5.6 Pro", and
Letwin, [arXiv:2607.24164](https://arxiv.org/abs/2607.24164)): $\psi_n \ge c(\log n)^{-1/4}$
via sharp variance inequalities feeding Klartag's Lichnerowicz route; a 13-Aug-2026 preprint
by Milman already cites it as known — unrefereed. Convention trap: many papers use the
reciprocal of the post's $\psi_n$.

## What this runs

`kls_conjecture.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with numpy/scipy/sympy/mpmath → four audit-verified papers → dossier →
**driver-created primary claim** + `verdict --set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) →
report + lint → `problem verdict` → PDF.

The instance program is exact where it can be: on isotropic polytopes with rational
moments (simplex, cube, cross-polytope, products), the best polynomial test function of
degree $\le k$ gives an exact rational lower bound on the Poincaré constant per body — and
the July-2026 preprint's key degree-4 inequality is exactly checkable per body and per
rational $M$ (a violation would refute the preprint; agreement is support only). The
proof track lays out the reduction chain (thin shell ⇒ KLS up to $\sqrt{\log n}$; KLS ⇒
thin shell ⇒ slicing) with established/claimed labels and asks precisely where
$\sqrt{\log n}$ resists becoming a constant.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact per-body Poincaré bounds, exact checks of the claimed
inequality, and a status sketch that keeps four layers apart — the theorem ladder, the two
newly proved consequences, the July 2026 claim, and the open conjecture —
`COMPUTATIONAL_EVIDENCE`, not a resolution. Calling slicing or thin shell "open" or
"up to polylog", or calling KLS proved, fails the epistemic bar this dossier sets.

## Selected references

- R. Kannan, L. Lovász, M. Simonovits (1995), *Isoperimetric problems for convex bodies
  and a localization lemma*, DCG 13.
- Y. T. Lee, S. S. Vempala, *The Kannan–Lovász–Simonovits conjecture*:
  [arXiv:1807.03465](https://arxiv.org/abs/1807.03465).
- B. Klartag, *Logarithmic bounds for isoperimetry and slices of convex sets*:
  [arXiv:2303.14938](https://arxiv.org/abs/2303.14938).
- B. Klartag, J. Lehec, *Affirmative resolution of Bourgain's slicing problem using Guan's
  bound*: [arXiv:2412.15044](https://arxiv.org/abs/2412.15044); *Thin-shell bounds via
  parallel coupling*: [arXiv:2507.15495](https://arxiv.org/abs/2507.15495).
- Q. Guan, arXiv:2412.09075; P. Bizeul, arXiv:2501.06854; Y. Chen, arXiv:2011.13661;
  R. Eldan, arXiv:1203.0893.
- July 2026 claims: Chen–Klartag [arXiv:2607.23307](https://arxiv.org/abs/2607.23307);
  Letwin [arXiv:2607.24164](https://arxiv.org/abs/2607.24164); cited by E. Milman,
  arXiv:2608.13052.
