# Campaign: Alon–Boppana for non-backtracking Ramanujan graphs

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified statement — the connected, exactly-fixed-$\rho$ version of
> the AIM question; small-graph minimisers, gadget families and the power-law/construction
> questions are internal tools. The driver designates the primary claim deterministically.
>
> Source: [AIM Problem List *Connecting communities via the block model*](http://aimpl.org/blockmodel/5/)
> (ed. A. Wein, AIM workshop May 2017; http only), Section 5, Problem 5.4 (L. Massoulié)
> with 5.1 and 5.5 as tools; the same lower-bound question is Problem 1.3(2) of the AIM
> list [*Spectral graph and hypergraph theory*](http://aimpl.org/spectralhypergraph/1/).

## The problem

Bordenave–Lelarge–Massoulié's non-backtracking notion of "Ramanujan" for irregular graphs
puts all NB eigenvalues except the Perron circle inside the disk of radius $\sqrt\rho$.
Is that the right threshold — does every large graph with NB Perron eigenvalue $\rho$ have
$|\lambda_2(B)| \ge \sqrt\rho - o(1)$, as Alon–Boppana says for regular graphs?

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open as posed for connected graphs with $\rho$ exactly fixed — and false for two literal
readings.** No proof of the lower bound in any form was found; the regular case is exact
(Ihara–Bass), and the upper side is a theorem for sparse Erdős–Rényi
([arXiv:1501.06087](https://arxiv.org/abs/1501.06087)) and random lifts
([arXiv:1502.04482](https://arxiv.org/abs/1502.04482)), with the universal cover sitting
exactly at $\sqrt\rho$ ([arXiv:0712.0192](https://arxiv.org/abs/0712.0192)). Creation-time
computation (independently re-run): among all 8025 connected graphs with $\delta \ge 2$ on
$\le 8$ vertices the ratio $|\lambda_2|/\sqrt\rho$ dips to $0.94705$; attaching a long cycle
keeps that ratio while $n \to \infty$ and $\rho_n \to \rho$ exponentially fast — so the
leafless-only wording of spectralhypergraph 1.3(2) and any "$\rho_n \to \rho$" reading of
5.4 are refuted by an explicit certified family, and disconnected graphs reach exact $\rho$
trivially. Random $k$-lifts of the minimiser, which preserve $\rho$ exactly, always had new
eigenvalues above $\sqrt\rho$ — the honest open question is the connected exact-$\rho$ one.

## What this runs

`nonbacktracking_ramanujan.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with **nauty** geng + numpy/scipy/sympy → four audit-verified
papers → dossier → **driver-created primary claim** + `verdict --set-primary` →
`prove --min-papers 5` → report + lint → `problem verdict` → PDF.

The instance program: NB spectra via the Ihara–Bass reduction over all small connected
graphs, exact integer-polynomial certificates for the minimisers and the gadget family
(`proof_submit`), lift experiments (the only known exact-$\rho$-preserving operation), and
side tables for power-law Chung–Lu graphs (5.1) and small irregular NB-Ramanujan graphs
(5.5). A connected exact-$\rho$ family with ratio bounded below 1 and a proof would refute
the primary claim; the proof track asks what an irregular Alon–Boppana argument needs.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: certified refutations of the two literal readings
(`VERIFIED_COUNTEREXAMPLE_TO_AUXILIARY_CLAIM`), exhaustive small-graph minima, lift
statistics, and a status sketch that keeps the regular (exact) case, the upper-side
theorems, the refuted readings and the open connected exact-$\rho$ statement apart —
`COMPUTATIONAL_EVIDENCE`, not a resolution.

## Selected references

- C. Bordenave, M. Lelarge, L. Massoulié, *Non-backtracking spectrum of random graphs:
  community detection and non-regular Ramanujan graphs*: [arXiv:1501.06087](https://arxiv.org/abs/1501.06087)
  (Ann. Probab. 2018).
- O. Angel, J. Friedman, S. Hoory, *The non-backtracking spectrum of the universal cover
  of a graph*: [arXiv:0712.0192](https://arxiv.org/abs/0712.0192).
- C. Bordenave, *A new proof of Friedman's second eigenvalue theorem and its extension to
  random lifts*: [arXiv:1502.04482](https://arxiv.org/abs/1502.04482).
- C. Glover, M. Kempton, *Spectral properties of the non-backtracking matrix of a graph*:
  [arXiv:2011.09385](https://arxiv.org/abs/2011.09385); M. Kotani, T. Sunada (2000).
- Stephan–Massoulié arXiv:2004.07408; Banks–Trevisan arXiv:1907.02539; Abbe–Ralli
  arXiv:2006.11248.
