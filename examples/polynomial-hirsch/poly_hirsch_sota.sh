#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Polynomial Hirsch Conjecture (literature-honest dossier)
# Source: a classical open problem in polyhedral combinatorics
#
# A literature-only dossier: the agent gathers and cites prior work and assembles
# a citation-honest report. It runs no numerical experiments.
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. (no numerics — the python-sci container is not built; see below)
#   4. (no single source paper — the agent gathers literature during prove)
#   5. write the problem statement to notes.md and create the dossier
#   6. run `opentorus prove --min-papers 10` (literature -> proof draft -> gap-fill)
#   7. build an honesty-linted report and export a PDF
#
# Prerequisites:
#   - `opentorus` on PATH (activate the env where you installed it)
#   - a tool-calling model; this script targets a local Ollama server on :11435
#   - (Docker is NOT required: this example runs no experiments)
#
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./poly_hirsch_sota.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# This is a literature-only example, so no container is built. To enable numerics,
# uncomment the block below (and install Docker):
#   mkdir -p docker
#   cat > docker/Dockerfile << 'DOCKERFILE'
#   FROM python:3.11-slim
#   RUN pip install --no-cache-dir numpy scipy mpmath sympy
#   WORKDIR /work
#   DOCKERFILE
#   opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
# (none — this is a classical conjecture; the agent gathers literature during prove.)

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Polynomial Hirsch Conjecture

Does there exist a polynomial p(n, d) that bounds the combinatorial (graph) diameter of every
d-dimensional convex polytope with n facets? The original Hirsch bound n - d was disproven
(Santos, 2010), but whether the diameter is bounded by *some* polynomial in n and d remains
open — a central question in polyhedral combinatorics and the theory of the simplex method
for linear programming.

Tags: polyhedral combinatorics, polytope diameter, simplex method.
NOTES
# `--structured` maps the single top-level '# ' heading to one dossier (PROBLEM-0001).
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
# The prove loop gathers and cites local papers and assembles a citation-honest
# report; it asserts no resolution. Reports cite only local PAPER-* artifacts, and
# missing bibliographic metadata is marked missing, never invented. --min-papers
# gates report building on gathering at least N local papers first.
opentorus --verbose prove "${TARGET}" --min-papers 10

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint            # honesty linter flags overclaiming
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
