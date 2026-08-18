# Campaign: The distance antimagic conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every finite graph with pairwise distinct
> neighbourhoods; exhaustive small-order certificates are internal tools. The driver
> designates the primary claim deterministically.
>
> Source: [AIM Problem List *Graph theory: structural properties, labelings, and connections to applications*](http://aimpl.org/graphstructureapp/1/)
> (ed. A. Dawkins; http only), Conjecture 1.45; origin Kamatchi–Arumugam (JCMCC 2013)
> and Simanjuntak–Wijaya ([arXiv:1312.7405](https://arxiv.org/abs/1312.7405)).

## The problem

Label the vertices of $G$ bijectively with $1, \dots, n$ and give each vertex the sum of
its neighbours' labels. Two vertices with the same open neighbourhood always tie, so
distinct neighbourhoods are necessary for a labelling with all sums distinct. The
conjecture is that they are also sufficient — for every graph. Everything known is class
by class.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Proved for paths, cycles, wheels, complete graphs, hypercubes, ladders, joins,
coronas, several Cartesian products, circulants with one generator, and more (see the
notes for the attribution details the counter-audit corrected — including that
$K_3 \square K_2$ *is* distance antimagic despite a too-strong printed condition in the
literature); exhaustively verified for all graphs of order $\le 8$ (Simanjuntak et al.,
Symmetry 2021). Nothing 2024–2026 beyond new classes and variants (local, inclusive,
$D$-antimagic on oriented graphs). Creation-time computation, done twice independently
through order 8: the $1, 1, 2, 5, 16, 78, 588, 8047, 205914$ distinct-neighbourhood
graphs on $1$–$9$ vertices are all distance antimagic — order 9 extends the published
range.

## What this runs

`distance_antimagic.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with **nauty** `geng` + CP-SAT/python-sat → four audit-verified
papers → dossier → **driver-created primary claim** + `verdict --set-primary` →
`campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint → `problem verdict` → PDF.

The instance program is exact end to end: geng streams graphs, an exact backtracking or
CP-SAT search finds a labelling or proves none exists, certificates are checked in
$O(m)$ and submitted via `proof_submit`; targeted order-10+ families (regular, bipartite,
near-twin-rich graphs) are the refutation territory. One certified UNSAT graph would
refute; a probabilistic or Nullstellensatz argument on the weight polynomial is the proof
route.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exhaustive certificates for small orders, hardness statistics versus
near-twin structure, and a status sketch that keeps the class-by-class theorem layer
apart from the open all-graphs statement — `COMPUTATIONAL_EVIDENCE`, not a resolution.
Open neighbourhoods only: $C_4$, $P_3$, $K_{n,n}$ are *not* distance antimagic (twins),
and $(a,d)$-distance antimagic is a much stronger, different notion.

## Selected references

- N. Kamatchi, S. Arumugam, *Distance antimagic graphs*, J. Combin. Math. Combin. Comput.
  84 (2013) 61–67.
- R. Simanjuntak, K. Wijaya, *On distance antimagic graphs*:
  [arXiv:1312.7405](https://arxiv.org/abs/1312.7405).
- S. Cichacz, D. Froncek, K. Sugeng, S. Zhou, *Group distance magic and antimagic graphs*:
  [arXiv:1309.7454](https://arxiv.org/abs/1309.7454).
- A. Abrar, R. Simanjuntak, *D-antimagic labelings on oriented linear forests* and
  *… of oriented star forests*: [arXiv:2501.05035](https://arxiv.org/abs/2501.05035),
  [arXiv:2501.05148](https://arxiv.org/abs/2501.05148) (introductions survey the state of
  the art).
- R. Simanjuntak et al., *Another antimagic conjecture*, Symmetry 13 (2021) 2071
  (exhaustive order $\le 8$).
