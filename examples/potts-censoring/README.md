# Campaign: Censoring for the ferromagnetic Potts model from a constant start

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified statement — every graph, $q$, $\beta$, schedule and
> censoring from a constant start; tiny-graph exhaustive searches are internal tools. The
> driver designates the primary claim deterministically.
>
> Source: [AIM Problem List *Markov chain mixing times*](http://aimpl.org/markovmixing/1/)
> (eds. A. Ben-Hamou, R. Gheissari, AIM workshop June 2016; http only), Problem 1.5
> (Y. Peres).

## The problem

Peres–Winkler's censoring inequality says that for monotone spin systems started at the
top, skipping updates can only slow mixing. The ferromagnetic Potts model with $q \ge 3$
colours is not monotone; Peres asked whether the inequality nevertheless holds when the
chain starts from a constant configuration ("all green").

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Peres–Winkler ([arXiv:1112.0603](https://arxiv.org/abs/1112.0603), CMP 2013)
covers monotone systems; Holroyd ([arXiv:1101.4690](https://arxiv.org/abs/1101.4690), JSP
2011) refuted the analogue for proper colourings, lazy transpositions and *anti*ferromagnetic
4-state Potts (large coupling), and states the ferromagnetic constant-start case is open;
Fill–Kahn ([arXiv:1109.6075](https://arxiv.org/abs/1109.6075)) generalize only to ordered
spins with positive correlations; Gheissari–Lubetzky ([arXiv:1607.02182](https://arxiv.org/abs/1607.02182))
use censoring only on the monotone FK dynamics. Nothing new through 2026. Creation-time
exact computation (independently re-run): zero violations on tiny graphs across
$\beta \in [0.3, 4]$ and all short schedules, while the controls (antiferro; non-constant
starts) reproduce the known violations.

## What this runs

`potts_censoring.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with numpy/sympy/networkx → four audit-verified papers → dossier →
**driver-created primary claim** + `verdict --set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) →
report + lint → `problem verdict` → PDF.

The instance program is exact: distributions on $q^n$ states as tensors, heat-bath updates
applied exactly, TV to $\pi$; a violation reduces to a single deleted update, so exhaustive
enumeration over short schedules is complete for that length; rational $e^\beta$ makes any
violation an exact certificate (`proof_submit`). The refutation side searches graphs and
schedules guided by Holroyd's mechanism; the proof track locates the monotonicity step in
Peres–Winkler and tests whether the random-cluster coupling can transfer censoring to Potts
from a constant start.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exhaustive exact verification on tiny graphs with certificates,
reproduced controls, adaptive searches for the largest negative gap, and a status sketch
keeping the monotone theorem, the antiferro/colouring counterexamples and the open ferro
constant-start question apart — `COMPUTATIONAL_EVIDENCE`, not a resolution.

## Selected references

- Y. Peres, P. Winkler, *Can extra updates delay mixing?*: [arXiv:1112.0603](https://arxiv.org/abs/1112.0603)
  (Comm. Math. Phys. 323, 2013).
- A. E. Holroyd, *Some circumstances where extra updates can delay mixing*:
  [arXiv:1101.4690](https://arxiv.org/abs/1101.4690) (J. Stat. Phys. 145, 2011).
- J. A. Fill, J. Kahn, *Comparison inequalities and fastest-mixing Markov chains*:
  [arXiv:1109.6075](https://arxiv.org/abs/1109.6075).
- R. Gheissari, E. Lubetzky, *Mixing times of critical 2D Potts models*:
  [arXiv:1607.02182](https://arxiv.org/abs/1607.02182).
