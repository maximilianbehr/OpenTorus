# The Graceful Tree Conjecture (campaign example)

## Primary target

**Every tree is graceful** (Ringel–Kotzig 1964): each tree on $m$ edges admits a vertex
labeling by distinct values in $\{0,\dots,m\}$ whose edge differences are exactly
$\{1,\dots,m\}$.

**Status audit (2026-08-14, fresh web check):** open. Computer-verified for all trees on
$\le 35$ vertices ([arXiv:1003.3045](https://arxiv.org/abs/1003.3045)); many restricted
classes proved; ["almost all trees are almost graceful"](https://arxiv.org/abs/1608.01577)
settles an asymptotic relaxation only. A 2007 claimed proof (arXiv:0709.2201) is not
accepted by the community and is classified as an unaccepted claim in the dossier.

## What this runs

Built from [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md): fresh workspace → config →
container (networkx, z3-solver, sympy) → three audit-verified source papers → dossier →
**driver-designated primary claim** (`problem claim` + `problem verdict --set-primary`) →
`campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint + **`problem verdict`** (scope check + terminal
classification) → PDF.

Dual track: the refutation side treats per-tree gracefulness as a finite CSP — an UNSAT
certificate for a single tree would be a machine-checkable counterexample
(`proof_submit(backend="smt")`); the proof side reproduces class constructions exactly and
mines invariants from exhaustive small-$n$ data. Fixed instances are tools; only the
derived campaign verdict can resolve anything, and only through verification artifacts.

## Prerequisites

Docker; a tool-calling model (defaults: local Ollama on 11434, override
`OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`); optional host z3 for the SMT verifier.
Resets `.opentorus/`.

## Run

```bash
bash graceful_tree.sh
```

## Honesty note

Every tree below 36 vertices is graceful, so a genuine counterexample would be large —
the realistic outcomes are certified class reproductions, exhaustive scoped sweeps, and
NUMERICAL/COMPUTATIONAL_EVIDENCE, never a resolution. The terminal classification is
derived, conservative, and cannot be talked upward.
