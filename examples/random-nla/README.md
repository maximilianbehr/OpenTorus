# Adaptive sketch size for randomized low-rank approximation

## Open problem

The randomized SVD / range finder (Halko–Martinsson–Tropp) approximates a matrix $A$ by
sketching it with a random embedding to dimension $\ell = k + p$, where $k$ is the target rank
and $p$ the oversampling. Choosing $\ell$ a priori requires knowledge of the spectral decay:
too small loses accuracy, too large wastes work. The RandNLA survey of Martinsson and Tropp
([arXiv:2002.01387](https://arxiv.org/abs/2002.01387)) discusses a posteriori error estimation
and adaptivity (randomized norm estimators) as the mechanism for choosing $\ell$ on the fly.

The problem targeted here: design and validate a computable a posteriori error estimate that
drives an **adaptive** sketch size $\ell$ achieving $\lVert A - \hat A\rVert \le \varepsilon$
with high probability, and characterize the oversampling $p$ needed as a function of the
spectral-decay profile (flat, polynomial, exponential). It is numerically explorable: for
synthetic matrices with controlled spectra, sweep $\ell$ against the true error and measure the
estimator's reliability — its failure probability and its tightness (estimate over true error).

## What this runs

The driver `adaptive_sketch_size.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`,
   `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
   The gap-fill no-progress backstop still ends a stuck run even with the caps at `inf`.
3. **Prepare environment** — write `docker/Dockerfile` (numpy, scipy, mpmath, sympy) and
   register the `python-sci` container via `opentorus env prepare`.
4. **Add the source paper** — `opentorus paper add https://arxiv.org/abs/2002.01387`.
5. **Create the dossier** — `opentorus problem new --from-markdown notes.md --structured`
   (the statement is written inline by the script via a heredoc).
6. **Prove** — `opentorus prove PROBLEM-0001 --min-papers 5` (literature → proof draft →
   gap-fill); the agent may write and run spectral-decay sweeps as `EXP-*` experiments.
7. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

## Prerequisites

- **Docker** — to build and run the `python-sci` container for the spectral-decay sweeps.
- **A tool-calling model** — the script targets a local Ollama model on port 11435
  (`gpt-oss:120b`); set `model.provider`, `model.name`, and `model.base_url` for your own
  setup. A local OpenAI-compatible server also works (cost then reads `$0 (local)`).
  OpenTorus refuses or warns up front if the configured model cannot call tools.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash adaptive_sketch_size.sh
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. The generated report is checked by the artifact-aware honesty linter, which flags
overclaiming and never upgrades evidence into proof. A run that gathers evidence but cannot
close every `[GAP-n]` ends with an honest, gapped sketch (status `HEURISTIC_ONLY` /
`EXPERIMENTAL_ONLY`) rather than a fabricated proof.
