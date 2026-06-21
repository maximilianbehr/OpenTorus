#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Adaptive sketch size for randomized low-rank approximation
# Source: Martinsson & Tropp, "Randomized Numerical Linear Algebra: Foundations
#         & Algorithms" (Acta Numerica 2020; arXiv:2002.01387)
#
# The randomized SVD / range finder (HMT) sketches A to dimension l = k + p
# (target rank k, oversampling p). Choosing l a priori needs the spectral decay;
# too small loses accuracy, too large wastes work. Can a computable a posteriori
# error estimate drive an ADAPTIVE l that hits a target error w.h.p., and what
# oversampling p does each decay profile (flat / polynomial / exponential) need?
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. build the python-sci container for the spectral-decay sweeps
#   4. register the source survey as a local PAPER-* artifact
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
# Usage: ./adaptive_sketch_size.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# A local OpenAI-compatible server works too (cost then reads "$0 (local)"):
#   opentorus config set model.provider openai
#   opentorus config set model.base_url http://localhost:11435   # add /v1 if your server needs it
opentorus config set model.provider ollama
opentorus config set model.name gpt-oss:120b            # or: gemma4:31b, gpt-4o-mini, …
opentorus config set model.base_url http://localhost:11435
opentorus config set model.timeout_seconds 1200         # raise for large local models
opentorus config set agent.style autonomous            # fewer prompts; destructive ops still confirmed
opentorus config set agent.max_steps inf               # no overall step cap (Ctrl-C to stop)
opentorus config set agent.prove_gap_fill_max_steps inf  # no separate gap-fill cap …
# … the no-progress backstop still ends a stuck gap-fill (see prove_gap_fill_no_progress_steps).
opentorus config set permissions.mode trusted          # auto-allow low/medium-risk actions

# --- 3. Numerical experiment environment ------------------------------------
# The agent writes and runs spectral-decay sweeps in a pinned container.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
# Register the survey as a local PAPER-* artifact (reports cite only local sources).
opentorus paper add https://arxiv.org/abs/2002.01387

# --- 5. Problem statement & dossier -----------------------------------------
# Quote 'NOTES' so the shell does not expand the LaTeX math ($...$, \ell, …).
cat > notes.md << 'NOTES'
# Problem: Adaptive sketch size for randomized low-rank approximation

**Source.** Per-Gunnar Martinsson, Joel A. Tropp, *Randomized Numerical Linear Algebra:
Foundations & Algorithms* (Acta Numerica 2020; [arXiv:2002.01387](https://arxiv.org/abs/2002.01387)),
the section on a posteriori error estimation and adaptivity.

The randomized SVD / range finder (HMT) approximates a matrix $A$ by sketching with a random
embedding to dimension $\ell = k + p$ ($k$ target rank, $p$ oversampling). Choosing $\ell$ a
priori needs knowledge of the spectral decay; too small loses accuracy, too large wastes work.
The survey discusses a posteriori error estimation and adaptivity (randomized norm estimators)
as the mechanism for choosing $\ell$ on the fly.

**Design and validate** a computable a posteriori error estimate that drives an adaptive sketch
size $\ell$ achieving $\lVert A - \hat A\rVert \le \varepsilon$ with high probability, and
characterize the oversampling $p$ needed as a function of the spectral-decay profile (flat,
polynomial, exponential).

**Numerically explorable.** For synthetic matrices with controlled spectra, sweep $\ell$ against
the true error and measure the estimator's reliability — its failure probability and tightness
(the ratio of the estimate to the true error).
NOTES
# `--structured` maps the single top-level '# ' heading to one dossier (PROBLEM-0001).
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
# The prove loop reads the dossier + local papers, may write/run experiments via
# exp_run (spectral-decay sweeps), and records claims/evidence/attempts. Numerical
# evidence only *supports* a claim; a verified claim requires a verification artifact.
# --min-papers gates proof drafting on gathering at least N local papers first.
opentorus --verbose prove "${TARGET}" --min-papers 5

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint            # honesty linter flags overclaiming
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
