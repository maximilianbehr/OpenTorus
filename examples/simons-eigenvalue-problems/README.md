# Simons workshop: linear systems and eigenvalue problems

## Open problem

Thirteen small-dimensional, numerically explorable open problems from "Linear Systems and
Eigenvalue Problems: Open Questions from a Simons Workshop"
([arXiv:2602.05394v3](https://arxiv.org/abs/2602.05394), 21 August 2026 — 47 numbered problems
in total; these are the ones probeable with small matrix experiments). The agent sets up one
dossier per problem, then attacks a chosen target by reading the local paper, writing and
running its own matrix experiments, and recording claims, evidence, and failed attempts. None of
these problems is claimed solved here; the example demonstrates the workflow.

Two further workshop problems are covered by standalone examples: 4.6 by
[nystrom-submodularity](../nystrom-submodularity/) and 6.3 (with its neighbors 6.4/6.5) by
[matrix-sign-approximation](../matrix-sign-approximation/).

**Status tracking (v3).** Version 3 is "updated to reflect the status of the open problems as of
August 20, 2026" and adds twelve dated update blocks. Five of the thirteen dossiers below are
affected, and [`notes.md`](notes.md) carries the reference and the retargeting for each. The
paper's wording is "claims to solve" / "claims to give a negative answer" — the seeds keep that
wording: a claimed resolution is literature to reproduce and check, and it never by itself
promotes a claim to `verified`. (4.6, the standalone nystrom-submodularity example, is likewise
claimed resolved in v3; 6.3-6.5 are untouched.)

| Dossier seed | Workshop problem | Topic | Status | Related scripts |
|---|---|---|---|---|
| 3.5  | Conditioning of Ritz values from random Krylov subspaces | bound $\kappa_V(Q^*AQ)$ in $n$ (counterexample search) | negative answer claimed (v3) | `test_ritz_conditioning.py`, `ritz_sweep.py`, `condition_experiment.py`, `condition_scaling.py`, `condition_decay.py` |
| 2.4  | CG vs randomized coordinate descent for $\lambda_i=i^{-p}$ | scaling law for stopping times | claimed solved (v3); broader question open | `cg_vs_rcd.py`, `run_cg_rcd_sweep.py` |
| 2.13 | Eigenvalue clustering vs GMRES iteration counts | construct example + non-normal counterexample | open | (agent-written) |
| 3.4  | When do Ritz values approximate invariant-subspace eigenvalues | empirical sufficient conditions | open | (agent-written) |
| 3.2  | Deterministic diagonal perturbation giving an eigenvalue gap | constructive search over diagonal patterns | open | `gap_experiment.py`, `test_gap.py`, `test_gap_patterns.py`, `test_ramp_gap.py`, `compare_patterns.py` |
| 2.20 | Forsythe conjecture for restarted CG | even/odd residual subsequences: single limits? (high-precision tracking + counterexample search) | claimed solved for $s=2$ (v3); $s\ge3$ open | (agent-written) |
| 2.15 | Updated CG residuals below machine precision | conditions vs stagnating examples (two-sided) | open | (agent-written) |
| 2.17 | Bits of precision for n-step CG backward error | empirical scaling law $p(n,\kappa,\epsilon)$ via variable-mantissa CG | open | (agent-written) |
| 3.6  | Ritz-value distribution across the numerical range | Haar vs Krylov subspaces, boundary/interior mass, attainability | open | (agent-written; reuses the 3.5 Arnoldi tooling) |
| 3.8  | O(kn) bidiagonal SVD in the MR3 family | failure-mode map for the three MRRR routes | open | (agent-written) |
| 4.2  | GECP on the fermionic kernel $e^{-t\omega}/(1+e^{-\omega})$ | empirical rate $k(\varepsilon,\Lambda)$ vs the two candidate bounds; pivot structure | claimed solved (v3) | (agent-written) |
| 4.3  | QRCP row selection on orthonormal columns | $\lVert Q(\mathcal{I},:)^{-1}\rVert_2$ poly-bounded? (adversarial Stiefel search) | negative answer claimed (v3) | (agent-written) |
| 4.7  | Volume sampling vs optimal column subset selection | worst-case ratio $x_k/y_k$ over rotations and spectra | open | (agent-written) |

The `scripts/` directory holds seed numerical experiments (NumPy/SciPy); the agent may write
and run more via `exp_run` during the prove loop.

## What this runs

The driver `simons_open_problems.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`, `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
3. **Prepare environment** — write `docker/Dockerfile` (numpy, scipy, mpmath, sympy) and register the `python-sci` container via `opentorus env prepare`.
4. **Add the source paper** — `opentorus paper add https://arxiv.org/abs/2602.05394`, then the
   eight v3 follow-up references (advisory: an unreachable host is a missing source, not a failed
   run) so a `REFERENCE_FACT` about a claimed resolution has a local source artifact to cite.
5. **Create the dossiers** — `opentorus problem new --from-markdown notes.md` (thirteen dossiers; 0001..0005 are the original five, 0006..0013 the second-pass extraction), then `opentorus problem list`.
6. **Prove** — `opentorus prove ${TARGET}` (literature → proof draft → gap-fill); the target defaults to `PROBLEM-0001`.
7. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

Use `opentorus problem list` to map dossier ids to workshop problems.

## Prerequisites

- **Docker** — to build and run the `python-sci` container for the numerical experiments.
- **A tool-calling model** — the script defaults to a local Ollama model on port 11434 (`gemma4:31b`); override with `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL` or edit the `opentorus config set model.*` lines.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
./simons_open_problems.sh                # attacks PROBLEM-0001 (Ritz conditioning, 3.5)
./simons_open_problems.sh PROBLEM-0002   # attacks another dossier
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. The generated report is checked by the artifact-aware honesty linter.
