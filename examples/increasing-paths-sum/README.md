# Campaign: Increasing paths in edge orderings — the Chung–Graham sum conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every graph, every edge ordering; exact
> small-graph minima are internal tools. The driver designates the primary claim
> deterministically.
>
> Source: [AIM Problem List *Graph Ramsey theory*](http://aimpl.org/graphramsey/1/)
> (AIM workshop Jan 2015, org. Conlon–Fox–Mubayi; http only), Problem 1.38 [Ron Graham].

## The problem

Order the edges of a graph $G$ as $1, \dots, |E|$ and let $t(v)$ be the length of the
longest path from $v$ along which the labels increase. Chung and Graham asked whether
$\sum_v t(v) \ge |E|$ for every graph and every ordering. For $K_n$ this would give
altitude $f(K_n) \ge (n-1)/2$ — Graham's first question on the same page, "is
$f(K_n) \ge cn$ for some $c > 0$?", which is also open: the best bounds are
$n^{1-o(1)} \le f(K_n) \le (1/2 + o(1))n$. The trail version is solved (Graham–Kleitman;
Winkler's token argument gives $\sum$ of trail lengths $= 2|E|$), and that is exactly the
argument that does not survive the "distinct vertices" requirement.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open** (both questions). Bucić–Kwan–Pokrovskiy–Sudakov–Tran–Wagner
([arXiv:1809.01468](https://arxiv.org/abs/1809.01468), Israel J. Math. 2020) prove
$f(K_n) \ge n^{1-o(1)}$ — not $\Omega(n)$ — and restate the sum question open;
Calderbank–Chung–Sturtevant's $(1/2 + o(1))n$ ordering is conjectured tight; Milans
([arXiv:1509.02143](https://arxiv.org/abs/1509.02143)) was the previous record; random
orderings are near-Hamiltonian (Lavrov–Loh; Martinsson
[arXiv:1605.07204](https://arxiv.org/abs/1605.07204)); nothing 2024–2026. Creation-time
computation, done twice independently: $f(K_3..K_6) = 2, 2, 3, 4$ (the $K_6$ value by
branch-and-bound), $\min\sum_v t(v) = 5, 8, 14, 20$ against $|E| = 3, 6, 10, 15$, no
violation on any graph with $\le 6$ vertices, and heuristic $K_7/K_8$ minima $28/36$
against $21/28$ — the ratio drifts toward $1$.

## What this runs

`increasing_paths_sum.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with **nauty** `geng`, gcc, CP-SAT → four audit-verified
papers → dossier → **driver-created primary claim** + `verdict --set-primary` →
`prove --min-papers 4` → report + lint → `problem verdict` → PDF.

The instance program is exact end to end: a DP for $t(v)$, exhaustive minima over
orderings for small graphs, branch-and-bound / CP-SAT for $K_6$–$K_7$, annealing for
$K_7$–$K_{12}$ and for the Calderbank–Chung–Sturtevant construction, explicit orderings
re-checked and submitted via `proof_submit`. One integer table with
$\sum_v t(v) < |E|$ would refute; a path-counting charging scheme in the spirit of
Winkler's token proof is the proof route.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact small values, heuristic minima, class lemmas (trees, cycles,
complete bipartite), and a status sketch that keeps the trail theorem and the
$n^{1-o(1)}$ bound apart from the open statements — `COMPUTATIONAL_EVIDENCE`, not a
resolution. Paths, not trails; length counts edges; $n^{1-o(1)}$ is not "linear".

## Selected references

- M. Bucić, M. Kwan, A. Pokrovskiy, B. Sudakov, T. Tran, A. Z. Wagner, *Nearly-linear
  monotone paths in edge-ordered graphs*: [arXiv:1809.01468](https://arxiv.org/abs/1809.01468).
- K. G. Milans, *Monotone paths in dense edge-ordered graphs*:
  [arXiv:1509.02143](https://arxiv.org/abs/1509.02143).
- J. De Silva, T. Molla, F. Pfender, T. Retter, M. Tait, *Increasing paths in edge-ordered
  graphs: the hypercube and random graphs*: [arXiv:1502.03146](https://arxiv.org/abs/1502.03146).
- A. Martinsson, *Most edge-orderings of $K_n$ have maximal altitude*:
  [arXiv:1605.07204](https://arxiv.org/abs/1605.07204).
- R. L. Graham, D. J. Kleitman, *Increasing paths in edge ordered graphs*, Period. Math.
  Hungar. 3 (1973); A. R. Calderbank, F. R. K. Chung, D. G. Sturtevant, *Increasing
  sequences with nonzero block sums and increasing paths in edge-ordered graphs*, Discrete
  Math. 50 (1984).
