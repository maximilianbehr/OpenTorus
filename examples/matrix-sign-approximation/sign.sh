#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Best polynomial approximation of the matrix sign function
# Source: arXiv:2504.01500
#
# The minimax error of degree-2^m-computable polynomials approximating sign(x)
# on [-1,-delta] u [delta,1]. The agent attacks it with literature + numerics.
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. build the python-sci container for the approximation experiments
#   4. register the source paper as a local PAPER-* artifact
#   5. write the problem statement to notes.md and create the dossier
#   6. run `opentorus prove` (literature -> proof draft -> gap-fill)
#   7. build an honesty-linted report and export a PDF
#
# Prerequisites:
#   - `opentorus` on PATH (activate the env where you installed it)
#   - Docker, for the python-sci container
#   - a tool-calling model; this script targets a local Ollama server on :11435
#
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./sign.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# Activate the env where you installed OpenTorus so `opentorus` is on PATH, e.g.:
#   source ~/GITHUB/OpenTorus/.venv/bin/activate

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
# Edit these for your provider/model. Defaults: a local Ollama model on :11435.
opentorus config set model.provider ollama
opentorus config set model.name gemma4:31b              # or: gpt-oss:120b, gpt-4o-mini, …
opentorus config set model.base_url http://localhost:11435
opentorus config set model.timeout_seconds 1200         # raise for large local models
opentorus config set agent.style autonomous            # fewer prompts; destructive ops still confirmed
opentorus config set agent.max_steps inf               # no overall step cap (Ctrl-C to stop)
opentorus config set agent.prove_gap_fill_max_steps inf  # no separate gap-fill cap
opentorus config set permissions.mode trusted          # auto-allow low/medium-risk actions

# --- 3. Numerical experiment environment ------------------------------------
# Experiments run in a pinned container; build a small scientific-Python image.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
# Register the paper as a local PAPER-* artifact (reports cite only local sources).
opentorus paper add https://arxiv.org/abs/2504.01500

# --- 5. Problem statement & dossier -----------------------------------------
# Quote 'NOTES' so the shell does not expand the LaTeX math ($$, $m$, $\delta$, …).
cat > notes.md << 'NOTES'
# Problem: Best polynomial approximation of the matrix sign function

Let $\Pi_{2^m}^*$ be the set of univariate polynomials whose corresponding matrix function
can be computed with $m$ matrix-matrix multiplications and an arbitrary number of matrix
additions and scalings. We consider the problem of determining the best such polynomial
that approximates the sign function in

$$
I := [-1,-\delta] \cup [\delta,1],
$$

$$
\varepsilon_m^* =
\min_{p \in \Pi_{2^m}^*}
\max_{x \in I}
|p(x) - \operatorname{sign}(x)|.
$$

What is the asymptotic error $\varepsilon_m^*$ as a function of $m$ and $\delta$?
NOTES
# `--structured` maps the single top-level '# ' heading to one dossier (PROBLEM-0001).
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
# The prove loop reads the dossier + local papers, may write/run experiments via
# exp_run, and records claims/evidence/attempts. Numerical evidence only *supports*
# a claim; a verified claim requires a verification artifact. --min-papers gates
# proof drafting on gathering at least N local papers first.
opentorus --verbose prove "${TARGET}" --min-papers 10

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint            # honesty linter flags overclaiming
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
