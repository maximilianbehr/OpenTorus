# Simons workshop: linear systems and eigenvalue problems

## Open problem

Five small-dimensional, numerically explorable open problems from "Linear Systems and
Eigenvalue Problems: Open Questions from a Simons Workshop" (arXiv:2602.05394). The agent sets
up one dossier per problem, then attacks a chosen target by reading the local paper, writing
and running its own matrix experiments, and recording claims, evidence, and failed attempts.
None of these problems is claimed solved here; the example demonstrates the workflow.

| Dossier seed | Workshop problem | Topic | Related scripts |
|---|---|---|---|
| 3.5  | Conditioning of Ritz values from random Krylov subspaces | bound $\kappa_V(Q^*AQ)$ in $n$ (counterexample search) | `test_ritz_conditioning.py`, `ritz_sweep.py`, `condition_experiment.py`, `condition_scaling.py`, `condition_decay.py` |
| 2.4  | CG vs randomized coordinate descent for $\lambda_i=i^{-p}$ | scaling law for stopping times | `cg_vs_rcd.py`, `run_cg_rcd_sweep.py` |
| 2.13 | Eigenvalue clustering vs GMRES iteration counts | construct example + non-normal counterexample | (agent-written) |
| 3.4  | When do Ritz values approximate invariant-subspace eigenvalues | empirical sufficient conditions | (agent-written) |
| 3.2  | Deterministic diagonal perturbation giving an eigenvalue gap | constructive search over diagonal patterns | `gap_experiment.py`, `test_gap.py`, `test_gap_patterns.py`, `test_ramp_gap.py`, `compare_patterns.py` |

The `scripts/` directory holds seed numerical experiments (NumPy/SciPy); the agent may write
and run more via `exp_run` during the prove loop.

## What this runs

The driver `simons_open_problems.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`, `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
3. **Prepare environment** — write `docker/Dockerfile` (numpy, scipy, mpmath, sympy) and register the `python-sci` container via `opentorus env prepare`.
4. **Add the source paper** — `opentorus paper add https://arxiv.org/abs/2602.05394`.
5. **Create the dossiers** — `opentorus problem new --from-markdown notes.md` (five dossiers), then `opentorus problem list`.
6. **Prove** — `opentorus prove ${TARGET}` (literature → proof draft → gap-fill); the target defaults to `PROBLEM-0001`.
7. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

Use `opentorus problem list` to map dossier ids to workshop problems.

## Prerequisites

- **Docker** — to build and run the `python-sci` container for the numerical experiments.
- **A tool-calling model** — the script targets a local Ollama model on port 11435 (`gpt-oss:120b`); set `model.provider`, `model.name`, and `model.base_url` for your own setup.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
./simons_open_problems.sh                # attacks PROBLEM-0001 (Ritz conditioning, 3.5)
./simons_open_problems.sh PROBLEM-0002   # attacks another dossier
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. The generated report is checked by the artifact-aware honesty linter.
