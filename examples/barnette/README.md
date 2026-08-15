# Barnette's Conjecture (campaign example)

## Primary target

**Every 3-connected cubic planar bipartite graph is Hamiltonian** (Barnette 1969).

**Status audit (2026-08-14, fresh web check):** open. Exhaustively verified for
$n \le 90$; Goodey's six-edge-face case proved; the *related* Barnette–Goodey conjecture
(cubic planar, faces $\le 6$) was proved by Kardoš (2020) — a settled neighbor the dossier
must not conflate with the target. Structural partials: facial 2-factors (Bagheri et al.
2021), [matching theory (arXiv:2202.11641)](https://arxiv.org/abs/2202.11641),
[sufficient conditions (arXiv:2309.09578)](https://arxiv.org/abs/2309.09578),
[Georges–Kelmans minimality (arXiv:2101.00943)](https://arxiv.org/abs/2101.00943).

## What this runs

Built from [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md): standard workflow with
driver-designated primary claim, dual-track task text, and the derived
`problem verdict` at the end. Refutation track: candidate generators (bipartite
expansions of Georges–Kelmans-type relatives) + per-candidate Hamiltonicity as a finite
SAT/SMT check with two independent encodings — a certified non-Hamiltonian candidate
would be the counterexample. Proof track: lemma validation (Goodey conditions, matching
lemmas) against exhaustive small-$n$ data, finite checks through `proof_submit`.

## Prerequisites

Docker; a tool-calling model (defaults: local Ollama on 11434, override
`OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`); optional host z3. Resets `.opentorus/`.

## Run

```bash
bash barnette.sh
```

## Honesty note

A counterexample needs $n > 90$ — the dossier says so up front, and search sweeps are
framed as obstruction-mining, not likely refutation. Realistic outcomes: certified lemma
reproductions, scoped exhaustive sweeps, COMPUTATIONAL/NUMERICAL_EVIDENCE. The verdict
layer cannot be talked upward.
