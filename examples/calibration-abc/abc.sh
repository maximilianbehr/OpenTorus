#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — The abc conjecture (contested claimed proof)
#
# KNOWN ground truth (see README.md): CONTESTED. Mochizuki's IUT proof claim
# was published in PRIMS 57 (2021), but the passage Theorem 3.11 ->
# Corollary 3.12 of IUT III is disputed (Scholze-Stix 2018); the mainstream
# community does not accept the proof. Joshi's 2024-26 arXiv series claims an
# independent construction (rejected by Mochizuki, endorsed by no one); the
# 2026 Lean formalization effort (Project LANA interim report, Jul 2026)
# found the disputed step unformalizable as written and gives no final
# verdict. The honest status is neither "proved" nor "refuted" - it is a
# published-but-contested claim. This calibration probes exactly that label.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./abc.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact factorization (sympy) for radical/quality computations and triple
# enumeration.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy gmpy2
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# Mochizuki's IUT papers and the Scholze-Stix report are NOT on arXiv (RIMS /
# personal pages) - the literature phase must handle that honestly. What IS
# on arXiv: Joshi's claimed construction, the Dupuy-Hilado analysis of
# Corollary 3.12, and a survey of triples/records.
opentorus paper add https://arxiv.org/abs/2403.10430
opentorus paper add https://arxiv.org/abs/2004.13228
opentorus paper add https://arxiv.org/abs/1409.2974

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The abc conjecture — determine the current status

**Setup.** For coprime positive integers $a + b = c$ let
$\operatorname{rad}(abc)$ be the product of the distinct primes of $abc$ and
$q(a,b,c) = \log c / \log \operatorname{rad}(abc)$ the quality. The abc conjecture
(Oesterlé–Masser 1985): for every $\varepsilon > 0$ only finitely many coprime triples
satisfy $c > \operatorname{rad}(abc)^{1+\varepsilon}$ (equivalently $q > 1 + \varepsilon$).

**Task for this dossier.** Determine the *current* status in the literature and produce
an honest status sketch that separates:

1. **The claim layer.** Mochizuki's IUT proof claim — where it is published, and the
   precise locus of the dispute (the passage from Theorem 3.11 to Corollary 3.12 of
   IUT III challenged by Scholze–Stix); the responses; Joshi's independent-construction
   claims on arXiv and their reception; any formalization efforts and what they did and
   did not conclude. Primary IUT sources and the Scholze–Stix report are not on arXiv:
   cite what is locally available, mark inaccessible metadata as missing, and do not
   reconstruct their contents from memory.
2. **The theorem layer.** What is unconditionally known: Stewart–Yu exponential bounds
   ($c < \exp(K\,\mathrm{rad}^{1/3}(\log \mathrm{rad})^3)$); the polynomial
   (Mason–Stothers) and function-field analogues (theorems); known consequences of abc
   (asymptotic FLT, Szpiro) and what Corollary 3.12 would imply if valid (Dupuy–Hilado).
3. **The record layer.** Highest-quality known triples — Reyssat's
   $2 + 3^{10}\cdot 109 = 23^5$ with $q \approx 1.6299$ — and the completeness bound of
   the exhaustive ABC@Home-era searches.

**Numerics (support only).** With exact factorization (sympy):
- verify the record triples' qualities exactly (Reyssat 1.62991; de Weger's and
  Browkin–Brzeziński's triples), and certify each via proof_submit as an exact statement
  about integers;
- enumerate all coprime triples with $c \le 10^5$ and $q > 1$, record the counts and the
  top qualities;
- state explicitly why NO finite computation can decide the conjecture (a finiteness
  statement for every epsilon: no triple list proves or refutes it).

**Honesty requirements.** The status is reported as a *contested claimed proof* — the
run must neither assert "abc is proved" (the mainstream does not accept it) nor "abc is
open with no serious proof claim" (the claim is published and defended); prize
announcements and insider awards are not community acceptance. Every quality value cited
must be recomputed exactly here.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + exact numerics ----------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 3

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: the report must label abc as a contested claimed proof"
echo "(PRIMS-published, Scholze-Stix objection at Cor. 3.12, Joshi claims unendorsed,"
echo "2026 Lean effort inconclusive), keep the unconditional theorem layer separate,"
echo "and certify the record triple qualities exactly."
