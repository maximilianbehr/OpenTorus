#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — Phase retrieval injectivity at N = 4M-5
#                                 (Vinzant's refined conjecture; an AI-generated
#                                 claimed proof of one half)
#
# KNOWN ground truth (see README.md): Randomstrasse101 Conjecture 19 - for
# N = 4M-5 complex Gaussian measurements, (a) the injectivity probability
# p_M is < 1 for every M, (b) p_M -> 0. Part (a) was CLAIMED in June 2026 by
# a 4-page note whose arXiv comment reads "AI generated, human verified"
# (arXiv:2606.17922; it exhibits a nonempty open set of non-injective A for
# every M >= 2, hence p_M < 1 for any absolutely continuous model). Part (b)
# is OPEN. Established layer: generic 4M-4 measurements are injective
# (Conca-Edidin-Hering-Vinzant, ACHA 2015); "4M-4 necessary" is FALSE
# (Vinzant, SampTA 2015: 11 = 4*4-5 injective vectors in C^4, with an exact
# certificate); a Jul-2026 preprint (Huang, arXiv:2607.27719, unrefereed)
# claims 10 vectors never suffice in C^4. This run tests the labels
# "claimed (AI-generated note)" vs "theorem" vs "false" vs "open", and asks
# for an EXACT certificate: injectivity or non-injectivity of a fixed A is a
# decidable real-algebraic statement (Bandeira-Cahill-Mixon-Nelson 2014,
# Lemma 9: A is non-injective iff a nonzero Hermitian Q of rank <= 2 is
# orthogonal to all a_k a_k^*).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./phase_retrieval.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact algebra for the rank-<=2 kernel criterion (sympy Groebner bases over
# Q(i)), numerical algebraic geometry / optimization for candidates (numpy,
# scipy), Monte Carlo over Gaussian frames.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy mpmath
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/1312.0158
opentorus paper add https://arxiv.org/abs/1502.04656
opentorus paper add https://arxiv.org/abs/2606.17922
opentorus paper add https://arxiv.org/abs/2607.27719

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Injectivity of complex phase retrieval at N = 4M−5 — determine the status and certify instances

**Setup.** $A \in \mathbb{C}^{N \times M}$ with rows $a_k$; the phase retrieval map is
$x \bmod \mathbb{T} \mapsto (|\langle a_k, x\rangle|^2)_{k \le N}$. **Conjecture 19
(Vinzant's refined conjecture, via Mixon's "Conjectures from SampTA" 2015; Randomstrasse101
Conjecture 19).** Let $N = 4M-5$ and draw $A$ at random with $\mathrm{im}(A)$ uniform on the
Grassmannian (e.g. iid complex Gaussian entries); let $p_M$ be the probability that the
map is injective. (a) $p_M < 1$ for all $M$; (b) $\lim_{M\to\infty} p_M = 0$.

**Task for this dossier.** Determine the *current* status and produce an honest status
sketch with four distinct labels:

1. **Theorem:** for generic $A$, $N = 4M-4$ measurements are injective
   (Conca–Edidin–Hering–Vinzant, arXiv:1312.0158, ACHA 2015), proving the sufficiency half
   of the Bandeira–Cahill–Mixon–Nelson $4M-4$ conjecture; over $\mathbb{R}$, $N \ge 2M-1$ is
   necessary and generic $2M-1$ suffice (complement property).
2. **False:** "$4M-4$ measurements are necessary" — Vinzant (arXiv:1502.04656, SampTA
   2015) exhibited $11 = 4\cdot4-5$ vectors in $\mathbb{C}^4$ that ARE injective, with an
   algebraic certificate; the exact minimum is also known for several other $M$.
3. **Claimed (unrefereed):** part (a) — a June-2026 four-page note (arXiv:2606.17922,
   arXiv comment "AI generated, human verified") shows a nonempty open set of
   non-injective $A \in \mathbb{C}^{(4M-5)\times M}$ for every $M \ge 2$, which yields
   $p_M < 1$ for any absolutely continuous model; and a July-2026 preprint
   (arXiv:2607.27719, unrefereed) claims no 10 vectors in $\mathbb{C}^4$ are injective, so
   that 11 would be exactly minimal for $M = 4$. Report both as claimed; do not upgrade
   either because the other cites it.
4. **Open:** part (b), $\lim p_M = 0$.

**Certification program (support only for the conjecture; theorems for each instance).**
By Bandeira–Cahill–Mixon–Nelson (2014, Lemma 9), $A$ is NOT injective iff some nonzero
Hermitian $Q$ of rank $\le 2$ satisfies $\langle a_k a_k^*, Q\rangle = 0$ for all $k$; the
orthogonal complement of $\{a_k a_k^*\}$ in Hermitian $M \times M$ matrices has real dimension
$M^2 - N$ ($= 5$ for $M = 4$, $N = 11$). Hence:
- for a fixed rational (Gaussian-integer) $A$, injectivity/non-injectivity is a decidable
  real-algebraic question — Gröbner bases over the $(M^2-N)$-dimensional kernel for the
  $3\times3$ minors, or numerical algebraic geometry followed by exact verification;
- a certified non-injective $A$ comes with explicit $x \ne \pm y$ (up to phase) and
  $|Ax| = |Ay|$ — recompute exactly and submit via proof_submit;
- reproduce Vinzant's injective 11-vector frame and its certificate;
- Monte Carlo over Gaussian $A$ for $M = 4, 5$ estimates $p_M$ numerically (evidence for
  part (b) only).

**Honesty requirements.** "AI generated, human verified" is an arXiv comment, not a
referee report — label accordingly, and do not treat mutual citations between two
preprints as peer review. Finite instances certify facts about those instances; part (b)
is a limit statement and stays open. Cite only locally parsed PAPER-* artifacts.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + certification run --------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 3

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: four labels kept apart - generic 4M-4 injective (theorem);"
echo "'4M-4 necessary' (false, Vinzant's 11-vector certificate reproduced); part (a) and"
echo "the 10-vector nonexistence (claimed, unrefereed 2026 preprints - one AI-generated);"
echo "part (b) (open) - plus at least one exact instance certificate via proof_submit."
