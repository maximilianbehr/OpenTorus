# Campaign: Erdős' distinct subset sums conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — a universal constant for every $n$; exact
> minima for small $n$ and record constructions are internal tools. The driver designates
> the primary claim deterministically.

## The problem

Is there a universal $c > 0$ such that every set of $n$ positive integers with pairwise
distinct subset sums has maximum element $\ge c \cdot 2^n$? Powers of two give $2^{n-1}$;
Conway–Guy-type constructions push the constant down to $0.22002$ (Bohman 1998); every
known lower bound is only $\Theta(2^n/\sqrt n)$. Erdős Problem #1 (\$500).

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Lower bounds: $\max A \ge \binom{n}{\lfloor n/2\rfloor}$ exactly and
$(\sqrt{2/\pi} - o(1))\,2^n/\sqrt n$ asymptotically (Dubroff–Fox–Xu,
[arXiv:2006.12988](https://arxiv.org/abs/2006.12988); the constant is Elkies–Gleason's,
reproved by Steinerberger, [arXiv:2208.12182](https://arxiv.org/abs/2208.12182); earlier
$\sqrt{3/(2\pi)}$ by Aliev, [arXiv:math/0503115](https://arxiv.org/abs/math/0503115)).
Upper bounds: Conway–Guy, Lunnon 1988, Bohman 1998 ($0.22002 \cdot 2^n$, large $n$).
Exact minima (OEIS A276661) known for $n \le 10$: $a(9) = 161$ (Grossman 2016),
$a(10) = 309$ (Dyson, Oct 2025, exhaustive); $a(11..13)$ only bounded above (Conway–Guy;
Popov 2025). A 2025 self-published, non-arXiv "resolution" is unrecognized and is recorded
as an unverified claim.

## What this runs

`distinct_subset_sums.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with sympy/OR-Tools/python-sat → three audit-verified papers →
dossier → **driver-created primary claim** + `verdict --set-primary` → `prove --min-papers 5`
→ report + lint → `problem verdict` → PDF.

Dual track: the refutation side searches for sum-distinct sets with small maximum at
$n = 11..14$ (a certified new record is first-class even though a single set refutes
nothing about a universal constant); the proof track reproduces the second-moment and
binomial bounds as exact checks, mines the known optimal sets for structure, and tests
candidate lemmas against the instance zoo — every exact fact certified via `proof_submit`
(sympy).

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: reproduced exact minima for small $n$ with certificates, verified
record constructions, a ratio table $a(n)/2^n$ that is still falling at $n = 10$, and a
correctly labelled literature map — `COMPUTATIONAL_EVIDENCE`, not a resolution. Neither a
new record set nor an exhaustive small-$n$ optimum touches the universal-constant statement.

## Selected references

- P. Erdős, problem #1 at erdosproblems.com; Erdős–Moser (1955) second-moment bound.
- J. H. Conway, R. K. Guy (1968), *Sets of natural numbers with distinct sums*, Notices AMS 15.
- W. F. Lunnon (1988), *Integer sets with distinct subset-sums*, Math. Comp. 50.
- T. Bohman (1996), Proc. AMS 124; (1998), Electron. J. Combin. 5 #R3.
- I. Aliev, *Siegel's Lemma and Sum-Distinct Sets*: [arXiv:math/0503115](https://arxiv.org/abs/math/0503115).
- Q. Dubroff, J. Fox, M. W. Xu, *A note on the Erdős distinct subset sums problem*:
  [arXiv:2006.12988](https://arxiv.org/abs/2006.12988).
- S. Steinerberger: [arXiv:2208.12182](https://arxiv.org/abs/2208.12182).
- OEIS [A276661](https://oeis.org/A276661) (minimal maxima), [A005318](https://oeis.org/A005318) (Conway–Guy).
