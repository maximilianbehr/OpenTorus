# The Caccetta–Häggkvist Conjecture (campaign example)

## Primary target

**For every $k \ge 2$**, every digraph on $n$ vertices with minimum out-degree $\ge n/k$
contains a directed cycle of length $\le k$ (Caccetta–Häggkvist 1978).

**Status audit (2026-08-14, fresh web check):** widely open — even $k=3$ (out-degree
$\ge n/3$ forces a directed triangle) is open. Proved for small independence number
([arXiv:1908.02902](https://arxiv.org/abs/1908.02902)); Shearer-type bounds give
$0.3465n$ for the triangle case, leaving the $[1/3, 0.3465]$ frontier. Survey:
[arXiv:1610.05292](https://arxiv.org/abs/1610.05292); rainbow strengthenings:
[arXiv:1804.01317](https://arxiv.org/abs/1804.01317).

## What this runs

Built from [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md): standard workflow,
driver-designated primary claim, dual-track task text, derived `problem verdict`.
The refutation track encodes fixed-$(n,k)$ instances in SAT/SMT: UNSAT is an exhaustive
certified result *for that instance* (`proof_submit(backend="smt")`, symmetry-breaking
constraints documented with satisfiability-preservation arguments); SAT would yield a
candidate counterexample for independent exact verification. The proof track reproduces
the Shearer computation and the independence-number boundary, mining invariants from the
exhaustive data.

## Prerequisites

Docker; a tool-calling model (defaults: local Ollama on 11434, override
`OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`); optional host z3. Resets `.opentorus/`.

## Run

```bash
bash caccetta_haggkvist.sh
```

## Honesty note

The known extremal candidates (blow-ups of short cycles) meet the bound with equality —
they demonstrate tightness, not truth, and the dossier says so. UNSAT sweeps are scoped
to their $(n,k)$; nothing generalizes silently. Realistic outcomes: certified instance
results, bound reproductions, COMPUTATIONAL/NUMERICAL_EVIDENCE.
