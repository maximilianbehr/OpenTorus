# Campaign: Constant-degree SoS refutation of k-colorability below Kesten–Stigum

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full asymptotic conjecture — for every $k$ and every constant SoS degree,
> no refutation below KS; degree-2 thresholds and small degree-4 SDPs are internal tools.
> The driver designates the primary claim deterministically.
>
> Source: [AIM Problem List *Connecting communities via the block model*](http://aimpl.org/blockmodel/3/)
> (ed. A. Wein, AIM workshop May 2017; http only), Section 3 "Hardness at the KS
> threshold", Problem 3.2 (C. Moore).

## The problem

Below the Kesten–Stigum bound of the planted $k$-coloring model — $d < (k-1)^2$ for
$G(n,d/n)$ — random graphs are already non-$k$-colorable, but can a constant-degree
sum-of-squares relaxation *certify* it? Banks–Kleinberg–Moore conjecture it cannot: the
statistical–computational gap of community detection, seen from the refutation side.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open as posed** for constant SoS degree $> 2$ at constant $d$. Degree 2 (Lovász $\vartheta$)
is settled and fails far above KS — it refutes only once $d \gtrsim 4(k-1)^2$
(Banks–Kleinberg–Moore [arXiv:1705.01194](https://arxiv.org/abs/1705.01194); Banks–Trevisan
[arXiv:1907.02539](https://arxiv.org/abs/1907.02539) for $G(n,d/n)$); quiet spectral
planting ([arXiv:2008.12237](https://arxiv.org/abs/2008.12237)) gives low-degree evidence
that hardness extends to $\approx 4(k-1)^2$. Rigorous SoS lower bounds exist only for dense
or $\log n \le d \ll \sqrt n$ regimes (Kothari–Manohar; Potechin–Xu STOC 2025, no arXiv,
hypothesis unconfirmed behind a paywall) — nothing at constant $d$; the closest technology
is ultra-sparse independent set ([arXiv:2406.18429](https://arxiv.org/abs/2406.18429)) and
graph-matrix norms on random regular graphs (Xu, arXiv:2411.14314). Note $d_{KS} = (k-1)^2$
($(k-1)^2+1$ regular), not the page's $k^2$.

## What this runs

`sos_coloring_ks.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with networkx/cvxpy/Clarabel/sympy → four audit-verified papers →
dossier → **driver-created primary claim** + `verdict --set-primary` →
`prove --min-papers 5` → report + lint → `problem verdict` → PDF.

The instance program: exact KS and degree-2 threshold tables, Hoffman/$\vartheta$ on samples
(creation-time reproduction: Hoffman refutes 3-col at $d = 16$ not $12$; 4-col at $36$ not
$20$; 5-col at $64$ not $30$), degree-4 SoS feasibility on small samples below KS with
exact rational pseudo-moment certificates via `proof_submit`. A refutation *family* with
proof would refute the claim; a pseudo-calibration + norm-bound argument would prove it —
neither is a computation.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: threshold tables, degree-4 feasibility rates with per-instance
certificates, and a status sketch that keeps theorem-grade (degree 2), evidence-grade
(quiet planting, low-degree) and open layers apart — `COMPUTATIONAL_EVIDENCE`, not a
resolution. Everything about "whp as $n \to \infty$" lives beyond any finite SDP.

## Selected references

- J. Banks, R. Kleinberg, C. Moore, *The Lovász theta function for random regular graphs
  and community detection in the hard regime*: [arXiv:1705.01194](https://arxiv.org/abs/1705.01194).
- J. Banks, L. Trevisan, *Vector colorings of random, Ramanujan, and large-girth irregular
  graphs*: [arXiv:1907.02539](https://arxiv.org/abs/1907.02539).
- A. S. Bandeira, J. Banks, D. Kunisky, C. Moore, A. S. Wein, *Spectral planting and the
  hardness of refuting cuts, colorability, and communities in random graphs*:
  [arXiv:2008.12237](https://arxiv.org/abs/2008.12237).
- P. Kothari, A. Potechin, J. Xu, *SoS lower bounds for independent set in ultra-sparse
  random graphs*: [arXiv:2406.18429](https://arxiv.org/abs/2406.18429); Potechin–Xu, STOC
  2025, DOI 10.1145/3717823.3718151.
