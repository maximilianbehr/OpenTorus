# A (7,5)-difference triangle set with scope ≤ 111

## Open problem

A $(7,5)$-difference triangle set consists of seven rows
$0 = a_{i,0} < a_{i,1} < \dots < a_{i,5} \le m$; each row contributes its 15 positive
pairwise differences, and all $7 \times 15 = 105$ differences must be pairwise distinct.
The smallest $m$ (the *scope*) for which this is possible is known to be at most 112;
**whether scope 111 is achievable is open**. Difference triangle sets appear in radio
astronomy, self-orthogonal codes, and ruler problems; optimal-scope tables live largely
in journal/handbook sources, so the run's first phase is a proper status audit.

## Why it fits OpenTorus

This is the most certificate-friendly problem in the collection — everything terminal is
finite and machine-checkable:

- a **construction** is seven rows of six integers, verified by two *independent*
  validators and re-checked exactly via `proof_submit(backend="sympy")`;
- a **nonexistence** result must carry a DRAT/LRAT/SMT certificate checked by an
  independent checker — a solver exit status is not a proof;
- **partial results** (excluded classes, sharpened bounds) must be exhaustively
  certified with their scope quantified.

The problem statement encodes a five-phase workflow (audit → dual validators →
structural analysis → three independent search approaches → rigorous output) and a
strict claim policy that maps 1:1 onto the dossier's epistemic ladder.

## What this runs

`dts.sh` follows the standard example workflow: fresh workspace → config (timeout 2400,
`max_steps inf`, trusted) → container with `z3-solver`, `python-sat`, and `ortools`
(CP-SAT) → dossier from the inline statement → `opentorus prove` (no `--min-papers`
quota — the primary tables are often paywalled, and the statement's Phase 1 handles the
audit honestly) → honesty-linted report + PDF. If `z3` is on the host PATH the SMT
verifier is enabled for `proof_submit(backend="smt")`.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults: local Ollama on 11434, override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`); optional **z3 on the host**. The script
  resets `.opentorus/`.

## Run

```bash
bash dts.sh
```

## Honesty note

The claim policy in the statement is the contract: a passing heuristic test is not a
proof, an incomplete search is not evidence of nonexistence, and the report's terminal
classification must be exactly one of the six categories. Both validators must agree
before any construction is presented; failed searches are preserved as first-class
attempts.
