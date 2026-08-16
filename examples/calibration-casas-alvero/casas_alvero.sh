#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — The Casas-Alvero conjecture
#
# KNOWN ground truth (see README.md): a claimed proof (Ghosh, arXiv:2501.09272,
# Jan 2025, revised Mar 2026) is under review. The agent must label the general
# claim as claimed/under review — AND can do genuine verification work: the
# conjecture is decidable degree by degree, so small degrees are honestly
# provable via sympy proof_submit. Statement below is neutral on status.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./casas_alvero.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set model.name "${OPENTORUS_MODEL:-gemma4:31b}"
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
opentorus config set model.timeout_seconds 1200
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted

# --- 3. Numerical experiment environment ------------------------------------
# Per-degree symbolic verification: resultants / Groebner elimination over Q.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers -------------------------------------------------------
opentorus paper add https://arxiv.org/abs/2501.09272
opentorus paper add https://arxiv.org/abs/2402.18717

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Casas-Alvero conjecture — status and small-degree verification

**Setup.** Let $K$ be a field of characteristic 0 and $f \in K[X]$ monic of degree $d \ge 1$.
The Casas-Alvero conjecture (2001) states: if $f$ shares a nontrivial common factor with
each of its derivatives $f^{(1)}, \dots, f^{(d-1)}$, then $f = (X - \alpha)^d$ for some
$\alpha \in K$.

**Classical landmarks.**
- True for degrees $d = p^k$ and $d = 2p^k$ ($p$ prime), via reduction mod $p$
  (Graf von Bothmer–Labs–Schicho–van de Woestijne and successors).
- Verified computationally for many small degrees; each fixed degree is a *decidable*
  elimination problem over $\mathbb{Q}$ (resultants / Gröbner bases).
- Finiteness structure: [arXiv:2402.18717](https://arxiv.org/abs/2402.18717).

**Task for this dossier.**
1. Determine the *current* status in the literature — including recent claimed proofs and
   their review state — and produce an honest status sketch separating "established for
   degree families", "claimed in general", and "peer-reviewed in general".
2. Genuine verification work: for small degrees ($d \le 6$ at least), carry out the
   per-degree elimination over $\mathbb{Q}$ symbolically (sympy resultants/Gröbner) and
   submit the checks via `proof_submit(backend="sympy")`, so each verified degree becomes a
   PROOF-* artifact with its exact scope ("degree d over characteristic 0") stated.

**Honesty requirements.** A verified degree is a theorem about that degree only; the general
conjecture's status must reflect review state, not preprint existence. Cite only locally
parsed PAPER-* artifacts.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + per-degree verification ------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 5

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: general claim labeled claimed/under review (Ghosh 2025/26);"
echo "small degrees verified as scoped sympy PROOF-* artifacts."
