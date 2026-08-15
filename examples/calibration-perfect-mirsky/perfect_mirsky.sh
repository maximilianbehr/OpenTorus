#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — The Perfect–Mirsky conjecture (n = 5)
#
# KNOWN ground truth (see README.md): the original conjecture is REFUTED for
# n = 5 — an explicit 5x5 doubly stochastic counterexample exists
# (Rivard-Mashreghi 2007; journal-only primary source). This run uses
# `prove --disprove`: the agent must find, reproduce, and VERIFY the
# counterexample (the COUNTEREXAMPLE_VERIFIED pathway), while reporting that
# the exact region Theta_n remains unknown. Also probes journal-only-source
# honesty: metadata that cannot be fetched is marked missing, never invented.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./perfect_mirsky.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Eigenvalue geometry of doubly stochastic matrices; the conjectured region
# (union of hulls of k-th roots of unity, k <= n) vs. sampled/constructed spectra.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Sources -------------------------------------------------------------
# The primary counterexample source (Rivard-Mashreghi 2007, Linear and
# Multilinear Algebra) is journal-only: there is deliberately no paper add
# here. The literature phase must locate what it can and mark unavailable
# full text honestly (missing metadata is marked missing, never invented).

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Perfect–Mirsky conjecture for n = 5 — find a refutation

**Setup.** Let $\Theta_n \subseteq \mathbb{C}$ be the set of all eigenvalues of all $n \times n$
doubly stochastic matrices (nonnegative, all row and column sums 1). Perfect and Mirsky
(1965) conjectured
$$
\Theta_n \;=\; \bigcup_{k=1}^{n} \Pi_k,
$$
where $\Pi_k$ is the convex hull of the $k$-th roots of unity.

**Classical landmarks.**
- $\Theta_n \supseteq \bigcup_{k\le n}\Pi_k$ is classical (Perfect–Mirsky); the conjecture
  is the reverse inclusion.
- True for small $n$ (the low-dimensional cases are settled affirmatively).

**Task for this dossier (disprove mode).** Refute the conjecture for $n = 5$ by
producing an explicit $5\times 5$ doubly stochastic counterexample, via EITHER route:

1. **Literature route.** Search for known refutations and reproduce the published
   counterexample matrix. The primary sources may be paywalled (metadata-only);
   in that case cite what is accessible honestly and fall back to route 2.
2. **Direct search route (no paper needed).** Hunt the counterexample yourself with
   exp_new/exp_run: parametrize $5\times 5$ doubly stochastic matrices (convex
   combinations of the 120 permutation matrices, or Sinkhorn-normalized positives),
   maximize the distance of eigenvalues to $\bigcup_{k\le 5}\Pi_k$, and refine
   candidates. The region boundary near the arc between the 4th- and 5th-root arcs
   is the known weak spot.

Either way, **verify** the candidate: certify that some eigenvalue lies outside
$\bigcup_{k \le 5}\Pi_k$ using exact or interval arithmetic (point-outside-polygon
certificates for each hull), and record it through the proper verification pathway.
Report honestly what remains open afterwards (the exact description of $\Theta_5$,
refined/modified versions of the conjecture).

**Honesty requirements.** A floating-point eigenvalue outside the region is a candidate,
not a counterexample — only a certified enclosure counts. If a source's full text is not
accessible, its metadata is marked as missing rather than reconstructed from memory.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Refutation run ------------------------------------------------------
# No --min-papers quota: the primary sources are paywalled (metadata-only), so a
# mandatory parsed-papers gate is unattainable and would block the direct
# counterexample search — the first real run confirmed exactly that (the
# draft-phase no-progress guard ended it with zero parsed papers).
opentorus --verbose prove "${TARGET}" --disprove

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: an explicit 5x5 doubly stochastic counterexample, its eigenvalue"
echo "certified outside the Perfect-Mirsky region (COUNTEREXAMPLE_VERIFIED), and an honest"
echo "note that the exact region Theta_5 remains unknown."
