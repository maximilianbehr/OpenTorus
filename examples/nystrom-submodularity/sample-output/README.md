# Sample output: a finished dossier (browsable without installing anything)

This directory is a complete, real OpenTorus dossier for the problem in the
parent example — including a **counterexample candidate found during its
preparation**. Start with [`dossier/report.md`](dossier/report.md).

## What it contains

- **An explicit counterexample candidate** ([`dossier/claims.jsonl`](dossier/claims.jsonl),
  `CLAIM-0003`): a 6×6 SDD positive-definite matrix, found by random search in
  exact rational arithmetic, on which the diminishing-error-reduction inequality
  for the nuclear Nyström error of `K = L^{-1}` **fails** — evidence against
  setting (2) of the open problem. Setting (1), SDDM, survived the same sweep
  (0/90 violations, `CLAIM-0001`).
- **Four reproducible experiments** (`dossier/experiments/EXP-*/`): manifest
  (command, seed, Python version, dependency hash), `run.sh`, and captured
  logs. `EXP-0003` re-verifies the candidate with a second, independent
  implementation (pure-Python fractions, no sympy). Re-run them with the
  scripts in [`scripts/`](scripts/).
- **Two failed attempts, kept as first-class obstructions**
  (`dossier/failed_attempts.jsonl`): a mis-formalization (testing `L` instead
  of `L^{-1}`) and a literal reading of "submodular" that fails empirically on
  the known inverse-Laplacian case. Dead ends are recorded, not discarded.
- **A hostile referee that refuses to certify** (`dossier/referee/REFEREE-0001.md`):
  verdict **block**, triggered by the recorded contradiction (`CLAIM-0002` is
  contradicted by `EXP-0002`). Independently of the block, the unverified
  candidate keeps every claim at heuristic/unverified status — the report's
  recommended next step is to *verify or refute the candidate*, not to
  celebrate it. Nothing here is `verified`, and nothing gets to claim it is.
  (Note the two distinct derived statuses: `report.md` derives
  `EXPERIMENTAL_ONLY` from the artifacts alone, while the referee derives
  `INVALID` from the open contradiction — both are shown, neither is hidden.)

## How it was made (provenance)

Driven by hand through the manual CLI surface (`opentorus problem new / attack /
claim / experiment --run / evidence / attempt / referee / report --lint`) with
the deterministic experiment scripts in `scripts/` — **no LLM was involved**, so
every artifact is reproducible. An agent run (`opentorus prove PROBLEM-XXXX
--disprove`) drives the same artifact model automatically. The honesty linter
passes on the report; the statuses are exactly what the artifacts support.

## Reproduce

The experiment scripts run standalone — no workspace needed. From this
directory (sympy is installed with OpenTorus; `verify_instance.py` is
stdlib-only):

```bash
python3 scripts/check_nystrom_submodularity.py --cls sddm --n 6 --trials 15 --pairs 6 --seed 7
python3 scripts/check_nystrom_submodularity.py --cls sdd  --n 6 --trials 15 --pairs 6 --seed 7
python3 scripts/convention_check_laplacian.py
python3 scripts/verify_instance.py
```

The sweeps are seeded and use exact rational arithmetic, so the violation
counts (SDDM: 0/90, SDD: 4/90) reproduce bit-for-bit. To rebuild the dossier
itself, copy `scripts/` into a fresh workspace (`opentorus init`) and replay
the commands recorded in the experiment manifests.

## Honesty note

A strict violation in exact arithmetic refutes the inequality *on that
instance, under this dossier's formalization* (stated in
`dossier/statement.md`, including the empirical convention check against the
known inverse-Laplacian case in `EXP-0004`). Whether it settles setting (2) of
the open problem depends on that formalization matching the intended one —
which is precisely why the claim is a `COUNTEREXAMPLE_CANDIDATE` and the
referee blocks: promotion to `COUNTEREXAMPLE_VERIFIED` requires an explicit
verification record.
