# Campaign: Seymour's second neighborhood conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every oriented graph; exhaustive small-order
> sweeps and bounded SAT searches are internal tools. The driver designates the primary
> claim deterministically.

## The problem

Every oriented graph (no loops, digons, or parallel arcs) has a vertex $v$ with
$|N^{++}(v)| \ge |N^{+}(v)|$: someone's "friends of friends" are at least as numerous as
their friends (Seymour, 1990). With 2-cycles allowed the statement is false — the
digon-free hypothesis is the problem.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Tournaments settled (Fisher 1996; Havet–Thomassé 2000, median orders — two
Seymour vertices when no vertex is dominated); quasi-transitive and star/matching-removal
classes settled. General constant $|N^{++}| \ge \gamma|N^{+}|$: $\gamma = 0.657298$
(Chen–Shen–Yuster 2003) improved to $0.715538$ (Huang–Peng,
[arXiv:2412.20234](https://arxiv.org/abs/2412.20234), Dec 2024 — first improvement in
20+ years). Min out-degree $\le 6$ (Kaneko–Locke 2001); $\delta^+ = 7$ computer-assisted
2026 preprint ([arXiv:2606.30588](https://arxiv.org/abs/2606.30588)). All orientations of
$G(n,p)$, $p < 1/2$, plus minimal-counterexample reductions
([arXiv:2403.02842](https://arxiv.org/abs/2403.02842), RSA 2025). A counterexample needs
$\ge 17$ vertices unconditionally ($\ge 19$ modulo the unrefereed $\delta^+{=}7$
preprint). One unverified full-proof claim (arXiv:2501.00614) has no confirmation. SNC
implies the Caccetta–Häggkvist case with min in- and out-degree $\ge n/3$.

## What this runs

`second_neighborhood.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with **nauty** (geng/directg/gentourng) + networkx +
python-sat + OR-Tools → three audit-verified papers → dossier → **driver-created primary
claim** + `verdict --set-primary` → `prove --min-papers 5` → report + lint →
`problem verdict` → PDF.

Dual track: the refutation side encodes "every vertex violates" as CP-SAT/SAT over the
17–20-vertex window that the reductions point at (near-regular, strongly connected,
large min out-degree) — one certified digraph refutes; the proof track exhausts small
orders via nauty streams with certificates, checks the median-order and constant-γ
statements on the instance zoo, and tests reduction lemmas against the data.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exhaustive verification with exact counts for small orders,
Seymour-vertex statistics, a correctly layered literature map (refereed classes / the
unrefereed δ⁺=7 preprint / the unverified proof claim) — `COMPUTATIONAL_EVIDENCE`, not a
resolution. Exhausting n ≤ 7 adds nothing below the known 17-vertex bound and is recorded
as reproduction, not discovery.

## Selected references

- P. Seymour (1990), via N. Dean, B. J. Latka, *Squaring the tournament — an open problem*.
- D. C. Fisher (1996), *Squaring a tournament: a proof of Dean's conjecture*, JGT 23.
- F. Havet, S. Thomassé (2000), *Median orders of tournaments*, JGT 35.
- Y. Kaneko, S. C. Locke (2001), Congr. Numer. 148.
- Huang–Peng: [arXiv:2412.20234](https://arxiv.org/abs/2412.20234);
  Sadhukhan–Sandeep–Sen: [arXiv:2606.30588](https://arxiv.org/abs/2606.30588);
  Espuny Díaz–Girão–Granet–Kronenberg: [arXiv:2403.02842](https://arxiv.org/abs/2403.02842).
