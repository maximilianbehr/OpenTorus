#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Submodularity of the nuclear Nyström error (SDD/SDDM)
# Source: open question on column subset selection for Nyström approximation
#
# Does submodularity of the nuclear Nyström error extend from inverse Laplacians
# to SDD / SDDM positive-definite matrices? The agent searches for a counterexample.
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. build the python-sci container for the matrix experiments
#   4. (no single source paper — the agent gathers literature during prove)
#   5. write the problem statement to notes.md and create the dossier
#   6. run `opentorus prove --disprove` (prioritise a counterexample search)
#   7. build an honesty-linted report and export a PDF
#
# Prerequisites:
#   - `opentorus` on PATH (activate the env where you installed it)
#   - Docker, for the python-sci container
#   - a tool-calling model; this script targets a local Ollama server on :11435
#
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./nystroem_submodularity.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# (none — this problem has no single source paper; the agent gathers relevant
#  literature during prove via lit_search.)

# --- 5. Problem statement & dossier -----------------------------------------
# Quote 'NOTES' so the shell does not expand the LaTeX math (\(L\), $\gamma$, …).
cat > notes.md << 'NOTES'
# Problem: Submodularity of the nuclear Nyström error for SDD/SDDM matrices

A new (and likely important) motivation for column subset selection comes from a problem of
Markov chain compression. One is presented with a large graph Laplacian \(L\) and wants a
reduced model computed in an interpolative fashion. To guarantee accuracy with respect to the
long-timescale dynamics of the random walk, it suffices to bound the Nyström approximation in
spectral or nuclear norm:

\[
\left\| K - K_{:, \mathcal{I}} K_{\mathcal{I}, \mathcal{I}}^{-1} K_{\mathcal{I}, :} \right\|_{\{2,*\}}
\]

with respect to a chosen subset \(\mathcal{I}\), where

\[
K = (L + \gamma I)^{-1}, \qquad \gamma > 0,
\]

in the limit \(\gamma \to 0^+\). We focus on the nuclear error. For inverse Laplacians (taking
care of null-space issues) the nuclear Nyström error is known to be a submodular function of
\(\mathcal{I}\) (excluding the empty set), which yields a worst-case greedy-vs-optimal bound
decaying like \(e^{-k/s}\) for \(k \geq s\). This question extends beyond Laplacians to
positive-definite matrices that are symmetric diagonally dominant (SDD) or SDD M-matrices (SDDM).

**Prove or disprove** the submodularity of the nuclear Nyström error when \(L\) is assumed,
in contrast to the above, to be

1. **SDDM and positive-definite**, or
2. **SDD and positive-definite**.
NOTES
# `--structured` maps the single top-level '# ' heading to one dossier (PROBLEM-0001).
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
# The prove loop reads the dossier + local papers, may write/run experiments via
# exp_run, and records claims/evidence/attempts. Numerical evidence only *supports*
# a claim; a verified claim requires a verification artifact. --disprove tells the
# loop to prioritise a counterexample / refutation.
opentorus --verbose prove "${TARGET}" --disprove

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint            # honesty linter flags overclaiming
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
