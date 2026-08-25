#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Simons workshop: linear systems & eigenvalue problems
# Source: "Linear Systems and Eigenvalue Problems: Open Questions from a Simons
#          Workshop" (arXiv:2602.05394v3, 21 Aug 2026 — 47 numbered problems;
#          v3 is "updated to reflect the status of the open problems as of
#          August 20, 2026" and five of the thirteen dossiers here are affected)
#
# Sets up one dossier per workshop problem (from the bundled notes.md) and lets
# the agent attack a chosen target with literature + its own numerical experiments.
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. build the python-sci container for the matrix experiments
#   4. register the source paper + the v3 follow-up references as local PAPER-* artifacts
#   5. create the thirteen dossiers from notes.md (deterministic, one per heading)
#   6. run `opentorus prove` on the target (literature -> draft -> gap-fill)
#   7. build an honesty-linted report and export a PDF
#
# Prerequisites:
#   - `opentorus` on PATH (activate the env where you installed it)
#   - Docker, for the python-sci container
#   - a tool-calling model; this script targets a local Ollama server on :11434 (override with OPENTORUS_MODEL / OPENTORUS_BASE_URL)
#   - the bundled notes.md (thirteen problems) and scripts/ (seed experiments)
#
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./simons_open_problems.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# Activate the env where you installed OpenTorus so `opentorus` is on PATH, e.g.:
#   source ~/GITHUB/OpenTorus/.venv/bin/activate

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
# Edit these for your provider/model. Defaults: a local Ollama model on :11434 (override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
opentorus config set model.provider "${OPENTORUS_PROVIDER:-ollama}"
opentorus config set model.name "${OPENTORUS_MODEL:-gemma4:31b}"              # or: gemma4:31b, gpt-4o-mini, …
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
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

# --- 4. Source paper + v3 follow-ups ----------------------------------------
# Register the paper as a local PAPER-* artifact (reports cite only local sources).
# The arXiv id is version-stripped on ingest, so this resolves the current version
# (v3 at the time of writing); the downloaded PDF is then SHA-256 pinned locally.
opentorus paper add https://arxiv.org/abs/2602.05394

# v3 credits claimed resolutions to the references below (see notes.md). Add them
# locally too, so the agent can cite them: a REFERENCE_FACT must point at a local
# source artifact. Non-arXiv hosts may be unreachable — that is a missing source,
# not a reason to abort the run, so each add is advisory.
for ref in \
  https://arxiv.org/abs/2606.02484 \
  https://arxiv.org/abs/2608.02852 \
  https://arxiv.org/abs/2607.13532 \
  https://arxiv.org/abs/2607.26863 \
  https://doi.org/10.5281/zenodo.21863274 \
  https://jarek.ai/papers/proof-of-the-forsythe-conjecture-for-s-2.pdf \
  https://yangpliu.github.io/repo/restarted-cg-two/paper.pdf \
  https://yangpliu.github.io/repo/two-step-ritz-obstruction/paper.pdf
do
  opentorus paper add "${ref}" || echo "note: could not add ${ref} (recorded as missing, not invented)"
done

# --- 5. Create the dossiers -------------------------------------------------
# notes.md holds thirteen problems, one per top-level '# ' heading; `--structured`
# maps each heading to one dossier deterministically (PROBLEM-0001..0013; 0001..0005
# are the original five, 0006..0013 the second-pass extraction).
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
# The prove loop reads the dossier + local papers, may write/run experiments via
# exp_run, and records claims/evidence/attempts. Numerical evidence only *supports*
# a claim; a verified claim requires a verification artifact.
# `prove` gates on the honesty linter: a report that still overclaims exits non-zero.
# That is a finding to read, not a crash — but under `set -e` it aborted this driver
# right here, before the report/verdict/PDF steps below ever ran. Keep the signal,
# finish the workflow, and exit with it at the end.
PROVE_RC=0
opentorus --verbose prove "${TARGET}" || PROVE_RC=$?

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Attack another problem with, e.g.: ./simons_open_problems.sh PROBLEM-0002"

exit "${PROVE_RC}"
