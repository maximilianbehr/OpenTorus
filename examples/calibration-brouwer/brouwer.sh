#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — Brouwer's Laplacian eigenvalue conjecture
#
# KNOWN ground truth (see README.md): a claimed proof appeared in 2026
# (Kothari-Tudose), with a wave of follow-up papers. The agent must find this
# in the literature and label it claimed/under review — not "open", not
# "settled fact". The statement below is deliberately neutral.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./brouwer.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
opentorus config set model.provider ollama
opentorus config set model.name "${OPENTORUS_MODEL:-muse-glimmer:30b}"
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
opentorus config set model.timeout_seconds 1200
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted

# --- 3. Numerical experiment environment ------------------------------------
# Exhaustive small-graph checks of the inequality (networkx + exact arithmetic).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers -------------------------------------------------------
opentorus paper add https://arxiv.org/abs/2606.12197
opentorus paper add https://arxiv.org/abs/2607.03388

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Brouwer's Laplacian eigenvalue conjecture — determine the current status

**Setup.** For a graph $G$ with $m$ edges, let $\mu_1 \ge \mu_2 \ge \dots \ge \mu_n$ be the
eigenvalues of its Laplacian $L = D - A$. Brouwer conjectured that for every
$1 \le k \le n$,
$$
\sum_{i=1}^{k} \mu_i \;\le\; m + \binom{k+1}{2}.
$$

**Classical landmarks.**
- The spectral majorization analogue of the Grone–Merris conjecture was proved by Bai
  (Grone–Merris–Bai theorem).
- Brouwer's inequality was long known for trees, unicyclic and bicyclic graphs, split
  graphs, cographs, regular graphs, and for $k \in \{1, 2, n-1, n\}$.

**Task for this dossier.** Determine the *current* status of Brouwer's conjecture in the
literature — including the most recent papers and any claimed proofs or equality-case
characterizations — and produce an honest status sketch distinguishing peer-reviewed
results, claimed preprints, and genuinely open parts. Corroborate with exhaustive
small-graph checks of the inequality (exact arithmetic) as support-only experiments.

**Honesty requirements.** "Claimed in a preprint" and "established" must remain distinct in
the report; cite only locally parsed PAPER-* artifacts; exhaustive checks state their size
bound and never generalize.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + numerics ---------------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 5

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: the report must surface the 2026 Kothari-Tudose proof claim and"
echo "label it claimed/under review; small-graph checks stay support-only."
