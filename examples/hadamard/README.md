# Campaign: The Hadamard conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — a Hadamard matrix of order $4k$ for *every*
> $k$; individual orders are internal tools. The driver designates the primary claim
> deterministically.

## The problem

Does a Hadamard matrix — an $n \times n$ $\pm 1$ matrix with $H H^{\mathsf T} = n I$ —
exist for every order $n = 4k$? Posed in substance by Hadamard (1893) after Sylvester's
$2^m$ constructions; the oldest open problem in the collection (130+ years).

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open in general** — and the finite frontier moved days before this audit was taken.
On 2026-08-12/13 a team at Anthropic (Alpöge, Voinov, Reynolds-Haertle, and the model
Claude) **announced** explicit Hadamard matrices for all twelve previously unknown orders
below 2000 (668, 716, 892, 1132, 1244, 1388, 1436, 1676, 1772, 1916, 1948, 1964), as raw
sign data in a social-media post. Third-party exact integer replay confirms the matrices;
there is **no arXiv paper and no peer review** at audit time, so the dossier carries the
announcement as *claimed, machine-checkable, unrefereed*. Before it, the smallest unknown
order was 668, standing since order 428 (Kharaghani–Tayfeh-Rezaie, published 2005).

The general conjecture is untouched by any finite list: known constructions (Sylvester,
Paley, Williamson-type, Goethals–Seidel), asymptotic existence of orders $k \cdot 2^t$
with $t$ logarithmic in $k$ (Craigen–Livinskyi line; explicit recent bound Du–Jiang,
[arXiv:2401.15381](https://arxiv.org/abs/2401.15381)), a positive-density result
(de Launey, [arXiv:1003.4001](https://arxiv.org/abs/1003.4001)), and a curated
construction database (Cati–Pasechnik,
[arXiv:2411.18897](https://arxiv.org/abs/2411.18897)) still cover a density-0 set of
orders. Williamson matrices fail to exist at $n = 35$ (Đoković 1993) and
$n = 47, 53, 59$ (Holzmann–Kharaghani–Tayfeh-Rezaie 2008) — ansatz limits, not
conjecture counterexamples.

## What this runs

`hadamard.sh` follows the campaign template: fresh workspace → config (timeout 2400s) →
container with numpy/sympy/python-sat → three audit-verified papers → dossier →
**driver-created primary claim** + `verdict --set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) →
report + lint → `problem verdict` → PDF.

Dual track with an honest asymmetry: the "refutation" of an order is a nonexistence
statement over $2^{n^2}$ matrices — provable only inside restricted ansätze (Williamson
SAT instances), never for the conjecture itself. The constructive track builds and
*exactly verifies* Sylvester/Paley/Goethals–Seidel matrices ($H H^{\mathsf T} = nI$ in
integer arithmetic, certified via `proof_submit`), maps which orders below 2000 each
method covers, and confronts the asymptotic-existence literature with what an all-$k$
statement would still need.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exactly verified construction tables, a correct coverage map, and a
literature layer that keeps three statuses apart — peer-reviewed constructions, the
unrefereed 2026 sub-2000 announcement, and the open general conjecture —
`COMPUTATIONAL_EVIDENCE`, not a resolution. A run that reports "all orders below 2000
are settled" as established fact fails the epistemic bar this dossier sets.

## Selected references

- J. Hadamard (1893), *Résolution d'une question relative aux déterminants*, Bull. Sci. Math. 17.
- D. Ž. Đoković (1993), *Williamson matrices of order 4n for n = 33, 35, 39*, Discrete Math. 115.
- W. de Launey, *On the asymptotic existence of Hadamard matrices*:
  [arXiv:1003.4001](https://arxiv.org/abs/1003.4001).
- C. Du, T. Jiang, *Golay complementary sequences … and asymptotic existence of Hadamard
  matrices*: [arXiv:2401.15381](https://arxiv.org/abs/2401.15381).
- D. Cati, D. Pasechnik, *A database of constructions of Hadamard matrices*:
  [arXiv:2411.18897](https://arxiv.org/abs/2411.18897).
- The August 2026 announcement: social-media release, third-party verified, unrefereed
  (status as of 2026-08-17; re-check at run time).
