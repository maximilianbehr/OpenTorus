# Campaign: The Erdős–Gyárfás conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every graph of minimum degree 3; individual
> graphs and exhaustive small-order sweeps are internal tools. The driver designates the
> primary claim deterministically.

## The problem

Every finite simple graph with minimum degree at least 3 contains a cycle whose length is
a power of 2 (Erdős–Gyárfás, posed ~1994/95, published 1997; Erdős offered \$100 for a
proof). Distinct from the same authors' generalized-Ramsey function and from
monochromatic-partition problems.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Settled classes: planar claw-free (Daniel–Shauger 2001); 3-connected cubic
planar (Heckman–Krakovski 2013); $K_{1,m}$-free with min degree $\ge m{+}1$ or max degree
$\ge 2m{-}1$ (Shauger 1998); $P_8$-, $P_{10}$-, $P_{13}$-free
([arXiv:2308.05675](https://arxiv.org/abs/2308.05675),
[arXiv:2410.22842](https://arxiv.org/abs/2410.22842)); diameter-2 with min degree 3
([arXiv:2508.19302](https://arxiv.org/abs/2508.19302)). Large *average* degree forces a
power-of-2 cycle (Liu–Montgomery, JAMS 2023,
[arXiv:2010.15802](https://arxiv.org/abs/2010.15802)) — an absolute-constant theorem
that does not decide minimum degree 3. A minimal counterexample is predominantly cubic
([arXiv:2605.22844](https://arxiv.org/abs/2605.22844)). Counterexample lower bounds:
$\ge 17$ vertices (Royle, Markström); no cubic counterexample $< 30$ vertices, with four
24-vertex cubic graphs whose only power-of-2 cycle length is 16 (Markström 2004); cubic
bipartite counterexamples need $\ge 60$ vertices (Tranquilli,
[arXiv:2608.02675](https://arxiv.org/abs/2608.02675), Aug 2026).

## What this runs

`erdos_gyarfas.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with **nauty** (geng/genbg, symlinked from the Debian
`nauty-*` binaries) + networkx + python-sat → three audit-verified papers → dossier →
**driver-created primary claim** + `verdict --set-primary` → `prove --min-papers 5` →
report + lint → `problem verdict` → PDF.

Dual track: the refutation side streams nauty-generated cubic and min-degree-3 graphs
through an exact cycle-spectrum routine and mines the Markström near-misses (graphs
whose only power-of-2 length is 16 — destroy the 16-cycles without creating 4s or 8s);
one certified graph would refute. The proof track exhausts small orders with certificates
via `proof_submit`, mines spectrum statistics for reduction lemmas, and confronts the
average-degree theorem with the min-degree-3 gap.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exhaustive small-order verification with exact counts, spectrum
statistics around the extremal 24-vertex graphs, a correctly layered literature map
(refereed classes vs. the unrefereed order-31 GitHub exclusion) —
`COMPUTATIONAL_EVIDENCE`, not a resolution. Cycle-length spectra of all small cubic
graphs say nothing about minimum degree 3 in general; the campaign treats a failed
counterexample search as exactly that.

## Selected references

- P. Erdős (1997), *Some old and new problems in various branches of combinatorics*,
  Discrete Math. 165/166.
- K. Markström (2004), *Extremal graphs for some problems on cycles in graphs*,
  Congr. Numer. 171.
- C. C. Heckman, R. Krakovski (2013), *Erdős–Gyárfás conjecture for cubic planar
  graphs*, Electron. J. Combin. 20(2) #P7.
- H. Liu, R. Montgomery, *A solution to Erdős and Hajnal's odd cycle problem*:
  [arXiv:2010.15802](https://arxiv.org/abs/2010.15802) (JAMS 2023).
- Hegde–Sandeep–Shashank: [arXiv:2410.22842](https://arxiv.org/abs/2410.22842);
  Hu–Shen: [arXiv:2308.05675](https://arxiv.org/abs/2308.05675);
  Carr: [arXiv:2508.19302](https://arxiv.org/abs/2508.19302),
  [arXiv:2605.22844](https://arxiv.org/abs/2605.22844);
  Tranquilli: [arXiv:2608.02675](https://arxiv.org/abs/2608.02675).
