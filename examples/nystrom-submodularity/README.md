# Submodularity of the nuclear Nyström error for SDD/SDDM matrices

> **Browse a finished dossier without installing anything:**
> [`sample-output/`](sample-output/) contains a complete real dossier for this
> problem — including an exact-arithmetic **counterexample candidate** for the
> SDD setting, four reproducible experiments, two recorded dead ends, and the
> hostile referee refusing to certify the unverified candidate.

## Open problem

Column subset selection for Nyström low-rank approximation can be analyzed through submodularity
of the approximation error. For inverse graph Laplacians, the nuclear Nyström error
`||K - K_{:,I} K_{I,I}^{-1} K_{I,:}||_*` with `K = (L + γI)^{-1}` in the limit `γ → 0⁺` is
reported to be a submodular function of the selected index set `I` (excluding the empty set),
giving a worst-case greedy-vs-optimal bound decaying like `e^{-k/s}` for `k ≥ s`. The open
question is whether this still holds when `L` is, instead of a Laplacian, (1) a symmetric
diagonally dominant M-matrix (SDDM) and positive-definite, or (2) symmetric diagonally dominant
(SDD) and positive-definite. The task is to **prove or disprove** it in each setting.

> **Convention caveat.** "Submodular" is sign-convention-dependent for a decreasing error
> function. An exact-arithmetic check on random inverse-Laplacian instances (see
> [sample-output/](sample-output/), `EXP-0004`) finds that the literal inequality
> `f(S∪{i})−f(S) ≥ f(T∪{i})−f(T)` fails there, while the diminishing-error-reduction reading
> (`≤`, i.e. the error *reduction* has diminishing returns — what the greedy bound needs)
> holds. The sample dossier therefore tests the diminishing-error-reduction reading.

## What this runs

The driver `nystroem_submodularity.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`, `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
3. **Prepare environment** — write `docker/Dockerfile` (numpy, mpmath, sympy) and register the `python-sci` container via `opentorus env prepare`.
4. **Create the dossier** — `opentorus problem new --from-markdown notes.md` (the statement is written inline by the script via a heredoc).
5. **Prove** — `opentorus prove PROBLEM-0001 --disprove` (prioritizes a counterexample search; literature → proof draft → gap-fill).
6. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

## Prerequisites

- **Docker** — to build and run the `python-sci` container for the numerical experiments.
- **A tool-calling model** — the script defaults to a local Ollama model on port 11434 (`gpt-oss:120b`); override with `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL` or edit the `opentorus config set model.*` lines.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash nystroem_submodularity.sh
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. The generated report is checked by the artifact-aware honesty linter.
