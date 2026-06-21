# Limited-memory polynomial methods for matrix functions

## Open problem

Five numerically explorable open problems from "Limited-memory polynomial methods for
large-scale matrix functions" (Güttel, Kressner, Lund; arXiv:2002.01682). These methods
approximate $f(A)\,b$ for a large matrix $A$ using cycles of fixed Krylov length $m$ (the
memory budget). The agent sets up one dossier per problem, then attacks a chosen target by
reading the local paper, writing and running its own matrix experiments, and recording claims,
evidence, and failed attempts. None of these problems is claimed solved here; the example
demonstrates the workflow.

| Dossier | Open problem | Focus | Source |
|---|---|---|---|
| PROBLEM-0001 | Optimal restart length for restarted Arnoldi for $f(A)b$ | predict the work-minimizing restart length $m$; explain the non-monotone dependence on $m$ | Sec. 4 |
| PROBLEM-0002 | A posteriori error estimation for limited-memory $f(A)b$ | a cheap, provable computable estimate $\eta_k \approx \lVert f(A)b - x_k\rVert$ for non-normal $A$ | Sec. 4.1 |
| PROBLEM-0003 | Efficient, stable evaluation of the first column of $f(H_m)$ | compute $f(H_m)\,e_1$ without forming all of $f(H_m)$ ($O(m^3)$/cycle) | Sec. 4.1 |
| PROBLEM-0004 | Loss of orthogonality in two-pass Lanczos for $f(A)b$ | quantify the convergence delay and design a limited-memory scheme that controls it | Sec. 4 |
| PROBLEM-0005 | Spectrum-adaptive explicit polynomial methods | adapt degree/region from observed Arnoldi/Lanczos data, no a priori spectral bounds | Sec. 3 |

The problems are numerically explorable (sweep $m$ against iterations/flops to tolerance, test
candidate estimators against the true error, …); the agent writes and runs experiments via
`exp_run` during the prove loop.

## What this runs

The driver `matrix_functions_open_problems.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`, `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
3. **Prepare environment** — write `docker/Dockerfile` (numpy, scipy, mpmath, sympy) and register the `python-sci` container via `opentorus env prepare`.
4. **Add the source paper** — `opentorus paper add https://arxiv.org/abs/2002.01682`.
5. **Create the dossiers** — `opentorus problem new --from-markdown notes.md --structured` (five dossiers), then `opentorus problem list`.
6. **Prove** — `opentorus prove ${TARGET}` (literature → proof draft → gap-fill); the target defaults to `PROBLEM-0001`.
7. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

Use `opentorus problem list` to map dossier ids to problems.

## Prerequisites

- **Docker** — to build and run the `python-sci` container for the numerical experiments.
- **A tool-calling model** — the script targets a local Ollama model on port 11435 (`gpt-oss:120b`); set `model.provider`, `model.name`, and `model.base_url` for your own setup.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
./matrix_functions_open_problems.sh                # attacks PROBLEM-0001 (optimal restart length)
./matrix_functions_open_problems.sh PROBLEM-0002   # attacks another dossier
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. A PDF export requires a tool-calling model to typeset the mathematics; without
one it produces a MathJax HTML report instead. The generated report is checked by the
artifact-aware honesty linter.
