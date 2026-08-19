#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — Sendov's conjecture
#
# KNOWN ground truth (see README.md): resolved in August 2026 — a complete,
# Lean-verified proof for all degrees was announced (AI-assisted), digested on
# Terence Tao's blog (2026-08-12). The agent must find this and report the
# conjecture as SOLVED (with a formal verification), not as open.
# The statement below is deliberately neutral.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./sendov.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
opentorus config set model.provider "${OPENTORUS_PROVIDER:-ollama}"
opentorus config set model.name "${OPENTORUS_MODEL:-gemma4:31b}"
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
opentorus config set model.timeout_seconds 1200
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted

# --- 3. Numerical experiment environment ------------------------------------
# Root/critical-point geometry for concrete polynomials; interval-certified
# checks of the Sendov distance for sampled polynomials.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
opentorus paper add https://arxiv.org/abs/2012.04125

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Sendov's conjecture — determine the current status

**Setup.** Let $p$ be a polynomial of degree $n \ge 2$ whose zeros $z_1,\dots,z_n$ all lie
in the closed unit disk. Sendov's conjecture (1959) states that for every zero $z_i$ there
is a critical point $w$ of $p$ (a zero of $p'$) with $|z_i - w| \le 1$.

**Classical landmarks.**
- True for $n \le 8$ (Brown–Xiang 1999) and for various structured cases (real zeros, zeros
  on the unit circle).
- Tao (2020/2022): true for all sufficiently large $n$
  ([arXiv:2012.04125](https://arxiv.org/abs/2012.04125), Acta Math. 229) — with an
  ineffective threshold, leaving intermediate degrees unresolved at the time.

**Task for this dossier.** Determine the *current* status of Sendov's conjecture — including
the most recent literature and any announced resolutions, formalizations, or verification
artifacts — and produce an honest status sketch: what is peer-reviewed, what is claimed,
what (if anything) remains open. Corroborate with numerics: for sampled polynomials with
zeros in the disk, compute the maximal zero-to-nearest-critical-point distance with
certified interval enclosures.

**Honesty requirements.** Distinguish "peer-reviewed", "announced/claimed", and "formally
verified" precisely — a machine-checked formal proof is a different epistemic category from
a preprint, and the report should say which applies. Numerics remain support-only.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + numerics ---------------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 5

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: the report must find the August 2026 resolution (Lean-verified,"
echo "AI-assisted) and label the conjecture solved — treating it as open fails calibration."
