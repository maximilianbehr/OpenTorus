# Campaign: Frankl's union-closed sets conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture; finite instances are internal tools. The
> driver designates the primary claim deterministically, so
> `GENERAL_CONJECTURE_PROVED/_REFUTED` are derivable only from verification artifacts.

## The problem

If a finite family of finite sets is union-closed ($A, B \in F \Rightarrow A\cup B \in F$)
and $F \ne \{\emptyset\}$, must some element belong to at least half of the members?
Posed by Frankl (1979); one of the best-known open problems in combinatorics.

## Status audit (2026-08-14, fresh web check)

**Open.** The Gilmer line (2022–2023) transformed the landscape: an entropy argument gives
a constant abundance bound, improved within days to $(3-\sqrt5)/2 \approx 0.38197$
([Chase–Lovett, arXiv:2211.11689](https://arxiv.org/abs/2211.11689); Alweiss–Huang–Sellke;
Sawin) and refined to $\approx 0.3824$
([arXiv:2212.12500](https://arxiv.org/abs/2212.12500)). Crucially, $(3-\sqrt5)/2$ is
**optimal for the approximate version** (Chase–Lovett), so closing the gap to $1/2$
needs new ideas — the campaign's proof track lives exactly in that gap. Claimed full
proofs circulate periodically without acceptance; the run re-checks and classifies them.

## What this runs

`frankl.sh` follows the campaign template: fresh workspace → config (timeout 2400s) →
`python-sci` container with z3 → three audit-verified papers → dossier from `notes.md` →
**driver-created primary claim** + `verdict --set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) →
report + lint → `problem verdict` (scope check + terminal classification) → PDF.

Dual track: the refutation side searches union-closed families with all abundances below
$1/2$ (exhaustive tiny grounds, SAT/z3 closures, annealing) — one verified family would
resolve the campaign, and a candidate is a finite, exactly checkable certificate. The
proof side reproduces the entropy bound per family, tests sharpening candidates against
the family zoo, and keeps every unresolved inference an explicit `[GAP-n]`.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash frankl.sh
```

## Honesty note

Realistic outcomes: a status sketch anchored in the Gilmer-line sources, certified
abundance statistics from exhaustive small-ground enumerations, and
`COMPUTATIONAL_EVIDENCE` / `NUMERICAL_EVIDENCE` classifications — not a resolution.
Decades of search found no counterexample; the approximate-version optimality result is
the honest explanation of why the last step is hard.

## Selected references

- P. Frankl (1979), the original conjecture (via extremal set theory surveys).
- J. Gilmer (2022), *A constant lower bound for the union-closed sets conjecture*.
- Z. Chase, S. Lovett (2022), [arXiv:2211.11689](https://arxiv.org/abs/2211.11689).
- Alweiss–Huang–Sellke (2022), [arXiv:2211.11731](https://arxiv.org/abs/2211.11731);
  Sawin (2022), [arXiv:2211.11504](https://arxiv.org/abs/2211.11504) — independent
  proofs of the $(3-\sqrt5)/2$ bound.
- Cambie (2022), [arXiv:2212.12500](https://arxiv.org/abs/2212.12500) — refinement to
  $\approx 0.3824$.
