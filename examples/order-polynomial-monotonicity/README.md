# Campaign: The Kahn–Saks order-polynomial monotonicity conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every finite poset, every $t$; exhaustive
> small-poset certificates are internal tools. The driver designates the primary claim
> deterministically.
>
> Source: [AIM Problem List *Ehrhart polynomials: inequalities and extremal constructions*](http://aimpl.org/ehrhartineq/2/)
> (ed. D. Hanely, AIM workshop May 2022; http only), Problem 2.12; origin Stanley, EC1,
> Exercise 3.163(b).

## The problem

Is the probability that a uniformly random map $P \to [t]$ is order-preserving,
$\Omega(P,t)/t^n$, nonincreasing in $t$ for every finite poset $P$? Eventually yes
(Stanley); trivially yes when the order polynomial has nonnegative coefficients — but
$\Omega$ can have negative coefficients from five elements on, and the question, raised
by Kahn and Saks and rated [5] by Stanley, is open in general.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Chan–Pak–Panova ([arXiv:2205.02798](https://arxiv.org/abs/2205.02798), SIAM
JDM 2023) name it the Kahn–Saks monotonicity conjecture, prove monotonicity along
$t, 2t, 4t, \dots$, show the width analogue is *increasing*, and give stronger implying
conjectures; Ferroni–Morales–Panova ([arXiv:2503.16403](https://arxiv.org/abs/2503.16403),
v3 Jul 2026) settle it for skew-shape cell posets and fence posets via coefficient
positivity; the Chan–Pak survey ([arXiv:2311.02743](https://arxiv.org/abs/2311.02743))
lists it open. Not to be confused with the Kahn–Saks *balancing* conjecture (the 2025
Aires–Kahn papers). Creation-time computation: no violation for any poset with $n \le 9$,
$t \le 12$; complete all-$t$ certificates for $n \le 8$; and the stronger pattern that
$D(t) = \Omega(t)(t+1)^n - \Omega(t+1)t^n$ has nonnegative coefficients in $t+1$ for
every non-antichain poset with $n \le 8$.

## What this runs

`order_polynomial_monotonicity.sh` follows the campaign template: fresh workspace →
config (timeout 2400s) → container with **nauty** `genposetg` + sympy → four
audit-verified papers → dossier → **driver-created primary claim** + `verdict
--set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint → `problem verdict` → PDF.

The instance program is exact end to end: $\Omega(P,t)$ from multichains of order ideals,
per-poset complete certificates ($D(t) \ge 0$ for $t \le T$ plus a root bound) via
`proof_submit`, exhaustive over all posets on $\le 7$–$8$ elements, then targeted searches
at 10–14 elements among posets with many negative $\Omega$-coefficients. One certified
pair $(P, t)$ would refute; the strengthening "$D(t+1)$ has nonnegative coefficients" is a
lemma candidate whose proof would settle the conjecture.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: complete certificates for small $n$, coefficient-sign statistics,
tests of the strengthenings, and a status sketch that keeps the theorem layer (eventual
decrease; $t \to kt$; positivity classes) apart from the open general statement —
`COMPUTATIONAL_EVIDENCE`, not a resolution.

## Selected references

- R. P. Stanley, *Enumerative Combinatorics I*, 2nd ed., Exercises 3.163–3.164.
- S. H. Chan, I. Pak, G. Panova, *Effective poset inequalities*:
  [arXiv:2205.02798](https://arxiv.org/abs/2205.02798) (SIAM J. Discrete Math. 2023).
- S. H. Chan, I. Pak, *Linear extensions of finite posets*: [arXiv:2311.02743](https://arxiv.org/abs/2311.02743).
- L. Ferroni, A. Morales, G. Panova, *Skew shapes, Ehrhart positivity and beyond*:
  [arXiv:2503.16403](https://arxiv.org/abs/2503.16403).
- F. Liu, A. Tsuchiya, *Stanley's non-Ehrhart-positive order polytopes*:
  [arXiv:1806.08403](https://arxiv.org/abs/1806.08403).
