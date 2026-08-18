# Campaign: Meunier's conjecture on s-stable Kneser graphs

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every $s$, $k$ and $n > sk$; individual
> $(s,n,k)$ instances (finite chromatic-number computations) are internal tools. The
> driver designates the primary claim deterministically.
>
> Source: [AIM Problem List *Albertson conjecture and related problems*](http://aimpl.org/albertson/8/)
> (ed. J. Zeng, AIM workshop Oct 2024; http only), Problem 8.1 (S. Zerbib); the conjecture
> is Meunier's (JCTA 2011).

## The problem

The $s$-stable Kneser graph $KG_s(n,k)$ keeps only the $k$-subsets of a cycle of length
$n$ whose elements are pairwise at cyclic distance $\ge s$, adjacent when disjoint. Lovász
($s = 1$) and Schrijver ($s = 2$) give $\chi = n - sk + s$; Meunier conjectured the same
formula for every $s$. The upper bound is trivial; the lower bound is topological
combinatorics at its sharpest.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open in general, partially resolved.** Proved: $s = 2$ (Schrijver); $n = sk+1$
(Meunier); all even $s$ (Chen, JGT 2015); $k = 2$ (Daneshpajouh–Meunier–Mizrahi,
[arXiv:2003.08255](https://arxiv.org/abs/2003.08255)); large $n$ for $s \ge 4$ (Jonsson
2012, unpublished and offline); off-by-one for $s = 3$ (Daneshpajouh–Osztényi,
[arXiv:1904.08219](https://arxiv.org/abs/1904.08219)); and, **new in July 2026**, $s = 3$
with $k = 3$ for all $n$ and with $k \ge 4$ for $n \ge k^3 + 3k^2$ (Chen–Parker–Zerbib,
[arXiv:2607.12912](https://arxiv.org/abs/2607.12912), preprint). Remaining: odd $s \ge 3$,
$k \ge 4$, $sk+1 < n$ below the thresholds. Neighbors: the almost-stable variant is
solved ([arXiv:1711.06621](https://arxiv.org/abs/1711.06621)); the hypergraph
$r$-stable conjecture was refuted for $r \ge 3$, leaving the graph case untouched.
Creation-time SAT runs (independently re-run) confirmed twelve open $s = 3$ instances
(e.g. $\chi(KG_3(16,4)) = 7$, $\chi(KG_3(24,7)) = 6$, $\chi(KG_3(19,5)) = 7$), each in
seconds to minutes; $KG_3(17,4)$ resisted a naive encoding.

## What this runs

`stable_kneser_chromatic.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with networkx + python-sat → four audit-verified papers →
dossier → **driver-created primary claim** + `verdict --set-primary` →
`campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint → `problem verdict` → PDF.

Every instance is a finite theorem: SAT with symmetry breaking on the cyclic action gives
the colouring (SAT side) and a DRAT-certified UNSAT for one colour fewer, verified via
`proof_submit`. The refutation side searches for colourings one below the conjectured
value on the open odd-$s$ instances ($\mathbb{Z}_n$-invariant colourings first); the proof
track probes the topological lower-bound machinery on small instances and asks why odd $s$
resists the even-$s$ argument.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: certified chromatic numbers for a growing set of open instances
(theorems for those instances), encoding improvements, and a status sketch keeping the
theorem layer, the unpublished/offline Jonsson result, the July 2026 preprint, and the
open residue apart — `COMPUTATIONAL_EVIDENCE` plus per-instance
`VERIFIED_PARTIAL_THEOREM`s, not a resolution.

## Selected references

- F. Meunier (2011), *The chromatic number of almost stable Kneser hypergraphs*, JCTA 118
  (the conjecture; not in the arXiv v1).
- P.-A. Chen (2015), *On the multichromatic number of s-stable Kneser graphs*, JGT 79.
- H. R. Daneshpajouh, F. Meunier, G. Mizrahi: [arXiv:2003.08255](https://arxiv.org/abs/2003.08255);
  H. R. Daneshpajouh, J. Osztényi: [arXiv:1904.08219](https://arxiv.org/abs/1904.08219);
  P.-A. Chen: [arXiv:1711.06621](https://arxiv.org/abs/1711.06621).
- W.-C. Chen, A. Parker, S. Zerbib, *The chromatic number of 3-stable Kneser graphs*:
  [arXiv:2607.12912](https://arxiv.org/abs/2607.12912).
