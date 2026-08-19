# Campaign: The 3/4 density threshold for global synchronization

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — for every ε a dense non-synchronizing graph;
> individual graphs and twisted-state certificates are internal tools (and, unusually for
> this collection, individually publishable when they beat the known bound). The driver
> designates the primary claim deterministically.
>
> Source: [Randomstrasse101](https://randomstrasse101.math.ethz.ch/posts/global-synchronization/)
> (ETH Zürich open-problems blog), Conjecture 5, with Conjectures 3–4 as neighbors;
> archived as [arXiv:2504.20539](https://arxiv.org/abs/2504.20539).

## The problem

Identical Kuramoto oscillators on a graph $G$ follow the gradient flow of
$\mathcal E(\theta) = \tfrac12\sum A_{ij}(1-\cos(\theta_i-\theta_j))$; $G$ is *globally
synchronizing* if $\mathcal E$ has no local minima besides the in-phase states. Dense
graphs synchronize; how dense is dense enough? Conjecture: the critical connectivity is
exactly $3/4$ — for every $\varepsilon > 0$ there is a graph with minimum degree
$\ge (3/4-\varepsilon)n$ that fails to synchronize.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** The upper half is a theorem — min degree $\ge 0.75(n-1)$ forces synchrony
(Kassabov–Strogatz–Townsend 2021, [arXiv:2105.11406](https://arxiv.org/abs/2105.11406)),
and $0.75$ is the limit of linear-stability arguments (McRae 2025,
[arXiv:2503.18801](https://arxiv.org/abs/2503.18801), agrees). The lower half stands at
$\mu_c > 0.6838$ (Yoneda–Tatsukawa–Teramae 2021, arXiv:2104.05954), after $0.6828$
(Townsend–Stillman–Strogatz, [arXiv:1906.10627](https://arxiv.org/abs/1906.10627)); the
TSS circulant families with density $\to 0.75$ have only degenerate second-order critical
points, not strict minima. Neighbors: random cubic graphs (Conjecture 3) open — random
$d$-regular graphs synchronize whp for $d \ge 35$ (McRae 2025, down from 600); the signed
Kuramoto conjecture (Conjecture 4) was **resolved** by McRae 2025 (Thm 3.2).

## What this runs

`kuramoto_density_threshold.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with numpy/scipy/sympy/mpmath/networkx → four
audit-verified papers → dossier → **driver-created primary claim** + `verdict
--set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint → `problem verdict` → PDF.

The instance program is the most certificate-friendly of the campaign set: twisted states
$\theta_j = 2\pi kj/n$ on circulant graphs are exact equilibria whose Hessian eigenvalues
are explicit trigonometric sums — a strict local minimum on a graph with minimum degree
$\mu(n-1)$ is an exact certificate (`proof_submit`, sympy) that $\mu_c > \mu$. Beyond
circulants: interval-Newton certification of general equilibria, exhaustive small-$n$
classification. Beating $0.6838$ with a certified graph would be a genuine new lower
bound; the refuting direction (every dense graph synchronizes) is a global landscape
theorem no computation can supply.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: reproduced certified dense non-synchronizing families, a
density-vs-stability frontier over circulant graphs, the strict-vs-degenerate distinction
made explicit, and a literature layer that keeps the theorem half, the certified lower
bound, and the resolved/open neighbors apart — `COMPUTATIONAL_EVIDENCE` or a
`VERIFIED_PARTIAL_THEOREM`-grade certificate, not a resolution. Numerically observed
"stable" states are candidates until the Hessian is certified positive definite on the
rotation complement.

## Selected references

- Y. Kuramoto (1975); S. Ling, R. Xu, A. S. Bandeira, arXiv:1809.11083.
- A. Townsend, M. Stillman, S. H. Strogatz, *Dense networks that do not synchronize and
  sparse ones that do*: [arXiv:1906.10627](https://arxiv.org/abs/1906.10627).
- M. Kassabov, S. H. Strogatz, A. Townsend, *Sufficiently dense Kuramoto networks are
  globally synchronizing*: [arXiv:2105.11406](https://arxiv.org/abs/2105.11406) (Chaos 2021).
- R. Yoneda, T. Tatsukawa, J. Teramae (2021), *The lower bound of the network connectivity
  guaranteeing in-phase synchronization*, Chaos 31; arXiv:2104.05954.
- A. D. McRae, *Benign landscapes for synchronization on spheres via normalized Laplacian
  matrices*: [arXiv:2503.18801](https://arxiv.org/abs/2503.18801).
- Abdalla–Bandeira–Kassabov–Souza–Strogatz–Townsend, *Expander graphs are globally
  synchronizing*: arXiv:2210.12788.
