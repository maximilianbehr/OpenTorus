# Campaign: Sidorenko's conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every bipartite $H$, every $G$; individual
> graphs (including the famous frontier instance) are internal tools. The driver
> designates the primary claim deterministically.

## The problem

For every bipartite graph $H$ and every graph $G$: $t_H(G) \ge t_{K_2}(G)^{e(H)}$ —
quasirandom graphs minimize the density of every bipartite pattern at fixed edge
density. Posed by Sidorenko (1993), with an equivalent form by Erdős–Simonovits; a
central open problem of extremal graph theory with deep ties to graph limits, entropy
methods, and property testing.

## Status audit (2026-08-14, fresh web check)

**Open in general** (audit amended 2026-08-15 after an independent cross-check).
Settled classes are extensive: trees, even cycles, complete
bipartite graphs, one-vertex-complete bipartite graphs, suitable blow-ups (for every
bipartite $H$ some blow-up $H^p$ is Sidorenko — Conlon–Lee,
[arXiv:1809.01259](https://arxiv.org/abs/1809.01259)), subdivisions/theta substitutions
([arXiv:2408.03491](https://arxiv.org/abs/2408.03491)), and broad recursive families
(Conlon–Kim–Lee–Lee line); an approximate version
holds for all bipartite $H$ (Conlon–Fox–Sudakov). The simplest unknown case is
$K_{5,5}$ minus a 10-cycle (isomorphic to the Möbius ladder on 10 vertices). No
counterexample is known.

## What this runs

`sidorenko.sh` follows the campaign template: fresh workspace → config (timeout 2400s) →
container with networkx → two audit-verified papers → dossier → **driver-created
primary claim** + `verdict --set-primary` → `prove --min-papers 5` → report + lint →
`problem verdict` → PDF.

Dual track: the refutation side optimizes weighted graphs $G$ against frontier patterns
$H$ (projected gradient on $t_H(G) - p^{e(H)}$), then completes numerical candidates to
exact rational witnesses — for fixed $H$ and rational $G$ the inequality is a finite
computation, certifiable via `proof_submit` (sympy). The proof track reproduces the
settled-class inequalities, probes which structural features separate settled from open
classes, and treats $K_{5,5}\setminus C_{10}$ as a lemma-grade tool, not the target.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash sidorenko.sh
```

## Honesty note

Realistic outcomes: a correctly classified map of the settled classes, exact
homomorphism-density experiments around the frontier, minimizer-landscape statistics —
`COMPUTATIONAL_EVIDENCE` / `NUMERICAL_EVIDENCE`, not a resolution. The approximate
version and the breadth of settled classes set a strong prior against a counterexample;
the campaign treats a failed search as exactly that.

## Selected references

- A. Sidorenko (1993), *A correlation inequality for bipartite graphs*, Graphs Combin. 9.
- D. Conlon, J. Fox, B. Sudakov (2010), *An approximate version of Sidorenko's
  conjecture*, GAFA 20.
- Blow-ups (Conlon–Lee): [arXiv:1809.01259](https://arxiv.org/abs/1809.01259);
  subdivisions/thetas: [arXiv:2408.03491](https://arxiv.org/abs/2408.03491).
