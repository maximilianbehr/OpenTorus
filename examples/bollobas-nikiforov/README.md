# The Bollobás–Nikiforov conjecture

## Open problem

For every graph $G \ne K_n$ with $m$ edges, clique number $\omega$, and adjacency
eigenvalues $\lambda_1 \ge \lambda_2 \ge \dots$, is
$\lambda_1^2 + \lambda_2^2 \le 2m(1 - 1/\omega)$? Proposed by Bollobás and Nikiforov (2007)
as a spectral strengthening of Turán-type bounds. Known for triangle-free, regular,
weakly perfect, Kneser, complete multipartite, and dense $K_4$-free graphs, and
asymptotically almost surely for random graphs
([arXiv:2407.19341](https://arxiv.org/abs/2407.19341),
[arXiv:2501.07137](https://arxiv.org/abs/2501.07137),
[arXiv:2603.26379](https://arxiv.org/abs/2603.26379)); **open in general**.

## What this runs

`bollobas_nikiforov.sh` follows the standard example workflow (fresh workspace → config →
container with networkx → three source papers → dossier → `opentorus prove --min-papers 5`
→ honesty-linted report + PDF). The agent can sweep graph space as `EXP-*` experiments:
exhaustive isomorph-free checks at small $n$, annealing on edge flips at larger $n$, always
tracking the extremal ratio. A candidate violation is a single finite graph whose
eigenvalues (certified enclosures of characteristic-polynomial roots) and clique number are
exactly recomputable — the `COUNTEREXAMPLE_VERIFIED` pathway.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults: local Ollama on 11434, override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`). The script resets `.opentorus/`.

## Run

```bash
bash bollobas_nikiforov.sh
```

## Honesty note

Exhaustive verification up to $n$ vertices is a theorem about graphs up to $n$ vertices —
the report must state the bound, never generalize it. Floating-point eigenvalues are not
evidence near equality cases; only certified enclosures count, and near-tight families
(complete multipartite) sit exactly at the danger zone.

## Selected references

- B. Bollobás, V. Nikiforov (2007), *Cliques and the spectral radius*, JCTB 97.
- Lin, Ning, Wu (2021), *Eigenvalues and triangles in graphs*, Combin. Probab. Comput. 30.
- Recent partial results: [arXiv:2407.19341](https://arxiv.org/abs/2407.19341),
  [arXiv:2501.07137](https://arxiv.org/abs/2501.07137),
  [arXiv:2603.26379](https://arxiv.org/abs/2603.26379)
