# The Komlós conjecture

## Open problem

Is there a universal constant $K$ such that any finite set of vectors $v_1,\dots,v_n$ of
Euclidean norm $\le 1$ (any dimension) admits signs $\varepsilon_i \in \{\pm1\}$ with
$\lVert\sum_i \varepsilon_i v_i\rVert_\infty \le K$? The best bound is Banaszczyk's
$O(\sqrt{\log n})$ from 1998 — made algorithmic by
[Dadush–Garg–Lovett–Nikolov (arXiv:1612.04304)](https://arxiv.org/abs/1612.04304) — and the
conjecture implies the Beck–Fiala conjecture for sparse set systems. **Open**: no universal
constant, and no unbounded family of instances either.

## What this runs

`komlos.sh` follows the standard example workflow (fresh workspace → config → container →
source paper → dossier → `opentorus prove --min-papers 5` → honesty-linted report + PDF).
The container ships `z3-solver`; if `z3` is on the host PATH the SMT verifier is enabled,
so exact sign-minimum statements for rational instances can be machine-checked via
`proof_submit(backend="smt")`.

Small cases are exactly decidable — the sign minimum for a fixed rational instance is an
exhaustive computation, so record instances become certified `PROOF-*` artifacts instead of
floating-point anecdotes.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults: local Ollama on 11434, override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`); optional **z3 on the host**. The script resets
  `.opentorus/`.

## Run

```bash
bash komlos.sh
```

## Honesty note

Certified records for bounded $n$ can never prove the conjecture, and a stagnating record is
not a proof either — both directions require actual arguments. The honest deliverable is a
status sketch plus a table of exactly-verified sign-minimum records with their instances,
each one reproducible from its `EXP-*` manifest.

## Selected references

- W. Banaszczyk (1998), *Balancing vectors and Gaussian measures of n-dimensional convex
  bodies*, Random Structures Algorithms 12.
- D. Dadush, S. Garg, S. Lovett, A. Nikolov (2016).
  [arXiv:1612.04304](https://arxiv.org/abs/1612.04304)
- J. Beck, T. Fiala (1981), *"Integer-making" theorems*, Discrete Appl. Math. 3.
