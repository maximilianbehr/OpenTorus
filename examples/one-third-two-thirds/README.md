# Campaign: The 1/3–2/3 conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every finite non-chain poset; exhaustive
> censuses and record instances are internal tools. The driver designates the primary
> claim deterministically.

## The problem

Every finite poset that is not a chain has a pair $x, y$ whose order is genuinely
uncertain: the fraction of linear extensions with $x$ before $y$ lies in $[1/3, 2/3]$
(Kislitsyn 1968; Fredman 1976; Linial 1984). Information-theoretically: comparison
sorting of partial orders always has a usefully balanced question. The bound $1/3$ would
be tight (the 3-element poset $T$ = 2-chain + isolated point).

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Exhaustively verified through $n = 14$ — a census of all 1.34 trillion
14-element posets confirming the Gold Partition Conjecture, hence 1/3–2/3 (Gupta,
[arXiv:2607.23926](https://arxiv.org/abs/2607.23926), Jul 2026, code+data; prior
frontiers $n \le 13$ De Loof et al. 2010, $n \le 11$ Peczarski 2006). Best general
constant: $(5-\sqrt5)/10 \approx 0.2764$ (Brightwell–Felsner–Trotter, Order 1995), after
Kahn–Saks $3/11$. Settled classes: width 2 (Linial 1984; sharpened by Sah, Combinatorica
2021, [arXiv:1811.01500](https://arxiv.org/abs/1811.01500)), semiorders, height 2,
nontrivial automorphism, 6-thin, series-parallel/N-free, forest cover graphs, several
lattice families, many-minimal-element/dense posets; asymptotic $\delta \to 1/2$ for
large width (Aires–Kahn, arXiv:2509.11549). **Width 3 open** (record $14/39$, Saks
1985). Extremal picture through $n=14$: $\delta = 1/3$ only for ordinal sums of
singletons and $T$; least value above $1/3$ is $37/106$; a gap is conjectured
(Peczarski; Chen's family approaches $\approx 0.3489$). Survey: Chan–Pak,
[arXiv:2311.02743](https://arxiv.org/abs/2311.02743) (EMS Surveys 2025) — note their
*sorting probability* is the opposite normalization of the same conjecture.

## What this runs

`one_third_two_thirds.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with **nauty** (`genposetg` streams Hasse diagrams up to
isomorphism) + sympy → three audit-verified papers → dossier → **driver-created primary
claim** + `verdict --set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint →
`problem verdict` → PDF.

Dual track: the refutation side hunts a poset with $\delta < 1/3$ — necessarily
$n \ge 15$, width $\ge 3$, automorphism-free, outside every settled class — with exact
rational re-evaluation of every candidate (linear-extension counting by DP over order
ideals is exact); the proof track reproduces the census on small $n$ with `proof_submit`
certificates, checks the extremal classification, and probes the width-3 frontier and the
conjectured gap above $1/3$.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exhaustive small-$n$ verification with exact rational certificates,
delta histograms and the extremal census, width-3 record statistics —
`COMPUTATIONAL_EVIDENCE`, not a resolution. The 2026 census is a preprint (labelled as
such), and no finite census bounds $\delta$ from below in general: Chen-type families
show values not attained at small $n$.

## Selected references

- S. S. Kislitsyn (1968); M. Fredman (1976); N. Linial (1984), SIAM J. Comput. 13.
- J. Kahn, M. Saks (1984), *Balancing poset extensions*, Order 1.
- G. Brightwell, S. Felsner, W. Trotter (1995), *Balancing pairs and the cross product
  conjecture*, Order 12.
- A. Sah, *Improving the 1/3–2/3 conjecture for width two posets*:
  [arXiv:1811.01500](https://arxiv.org/abs/1811.01500) (Combinatorica 2021).
- S. H. Chan, I. Pak, *Linear extensions of finite posets*:
  [arXiv:2311.02743](https://arxiv.org/abs/2311.02743) (EMS Surveys 2025), §13.
- A. Gupta, *Balance constants, majority cycles, and the Gold Partition Conjecture
  through fourteen elements*: [arXiv:2607.23926](https://arxiv.org/abs/2607.23926).
