# Matrix sign function: best polynomial approximation in $\Pi_{2^m}^*$

## Open problem

Let $\Pi_{2^m}^*$ be the set of univariate polynomials whose corresponding matrix function can be
evaluated with $m$ matrix-matrix multiplications (plus arbitrary matrix additions and scalings).
The problem is to determine the best such polynomial approximating the sign function on
$I := [-1,-\delta] \cup [\delta,1]$, i.e. the minimax error
$\varepsilon_m^* = \min_{p \in \Pi_{2^m}^*} \max_{x \in I} |p(x) - \operatorname{sign}(x)|$, and to
characterize its asymptotic behavior as a function of $m$ and $\delta$ (arXiv:2504.01500).

## What this runs

The driver `sign.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`, `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
3. **Prepare environment** — write `docker/Dockerfile` (numpy, mpmath, sympy) and register the `python-sci` container via `opentorus env prepare`.
4. **Create the dossier** — `opentorus problem new --from-markdown notes.md` (the statement, with LaTeX math, is written inline by the script via a single-quoted heredoc), then `opentorus problem show`.
5. **Add the source paper** — `opentorus paper add https://arxiv.org/abs/2504.01500`.
6. **Prove** — `opentorus prove PROBLEM-0001 --min-papers 10` (literature → proof draft → gap-fill).
7. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

## Prerequisites

- **Docker** — to build and run the `python-sci` container for the numerical experiments.
- **A tool-calling model** — the script targets a local Ollama model on port 11435 (`gpt-oss:120b`); set `model.provider`, `model.name`, and `model.base_url` for your own setup.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash sign.sh
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. The generated report is checked by the artifact-aware honesty linter.
