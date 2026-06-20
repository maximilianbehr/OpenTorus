# Universal convergence of backward error in linear-system solvers

## Open problem

For an invertible matrix $A$ and right-hand side $b$, the relative backward error of an
approximate solution $x$ is $\mathrm{berr}_{A,b}(x) = \min_{\tilde{A}} \|\tilde{A}-A\|_2 / \|A\|_2$
subject to $\tilde{A}x = b$. Dereziński, Nakatsukasa and Rebrova
([arXiv:2604.16075](https://arxiv.org/abs/2604.16075)) establish universal (condition-number-free)
backward-error rates for PSD systems and randomness-dependent rates for general systems. The open
question targeted here is whether *any* randomness (e.g. a Gaussian perturbation of $A$) is
*necessary* for a backward-error rate independent of $\kappa(A)$ in the general (non-PSD) case —
equivalently, whether a deterministic Krylov-type method can attain $\mathrm{berr}_{A,b}(x_k) \le
f(k) \to 0$ with $f$ independent of both $\kappa(A)$ and $n$, or whether a lower bound rules it out.

## What this runs

The driver `minberr_backward_error.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`, `agent.max_steps inf`, `permissions.mode trusted`.
3. **Prepare environment** — write `docker/Dockerfile` (numpy, scipy, mpmath, sympy) and register the `python-sci` container via `opentorus env prepare`.
4. **Add the source paper** — `opentorus paper add https://arxiv.org/abs/2604.16075`.
5. **Create the dossier** — `opentorus problem new --from-markdown notes.md` (the statement is written inline by the script via a heredoc).
6. **Prove** — `opentorus prove PROBLEM-0001 --min-papers 10` (literature → proof draft → gap-fill).
7. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

## Prerequisites

- **Docker** — to build and run the `python-sci` container for the numerical experiments.
- **A tool-calling model** — the script targets a local Ollama model on port 11435 (`gpt-oss:120b`); set `model.provider`, `model.name`, and `model.base_url` for your own setup.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash minberr_backward_error.sh
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. The generated report is checked by the artifact-aware honesty linter.
