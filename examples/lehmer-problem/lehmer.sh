#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Lehmer's Mahler measure problem (1933)
# Source: C. Smyth, "The Mahler measure of algebraic numbers: a survey",
#         arXiv:math/0701397.
#
# Problem (Lehmer). Is there a constant delta > 0 such that every monic integer
# polynomial p that is not a product of cyclotomics and powers of x satisfies
# M(p) >= 1 + delta, where M(p) = prod max(1, |root|) is the Mahler measure?
# Record since 1933: Lehmer's degree-10 polynomial with M ~ 1.176280818.
# Known: Smyth 1971 settles the nonreciprocal case (M >= 1.3247...);
# Dobrowolski gives M >= 1 + c (loglog d / log d)^3. OPEN in general.
#
# Mahler measures of concrete polynomials are interval-certifiable, so record
# tables become verification artifacts.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./lehmer.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# High-precision root finding (mpmath), sweeps over sparse/reciprocal integer
# polynomial families, certified Mahler-measure enclosures.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
opentorus paper add https://arxiv.org/abs/math/0701397

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Lehmer's Mahler measure problem

**Source.** D. H. Lehmer, *Factorization of certain cyclotomic functions*, Ann. of Math. 34
(1933). Survey: C. Smyth, [arXiv:math/0701397](https://arxiv.org/abs/math/0701397).

**Setup.** For a monic $p \in \mathbb{Z}[x]$ with roots $\alpha_i$, the Mahler measure is
$$
M(p) \;=\; \prod_i \max(1, |\alpha_i|).
$$
$M(p) = 1$ iff $p$ is a product of cyclotomic polynomials and a power of $x$ (Kronecker).

**Problem (Lehmer).** Is there $\delta > 0$ such that every other monic integer polynomial
satisfies $M(p) \ge 1 + \delta$? Equivalently: is
$\inf\{M(p) : M(p) > 1\} > 1$ — and is it attained by Lehmer's polynomial
$$
\ell(x) = x^{10} + x^9 - x^7 - x^6 - x^5 - x^4 - x^3 + x + 1,
\qquad M(\ell) \approx 1.176280818\,?
$$

**Known.**
- Smyth (1971): for **nonreciprocal** $p$, $M(p) \ge \theta_0 \approx 1.324717$ (the plastic
  number) — the problem is open only for reciprocal polynomials.
- Dobrowolski (1979): $M(p) \ge 1 + c\,(\log\log d / \log d)^3$ for degree $d$ — the best
  general lower bound shape to date.
- Extensive computer searches over 90+ years have found no measure in $(1, 1.176280818)$;
  Lehmer's degree-10 record stands.

**Open.** The uniform gap $\delta > 0$ (and whether $\ell$ is the minimizer).

**Numerically explorable.**
1. Certified record tables: for candidate reciprocal families (sparse, height-1, small
   degree), compute $M(p)$ with certified interval enclosures (root isolation + interval
   products) and submit via `proof_submit(backend="interval")` — "no measure in
   $(1, 1.17628)$ within family F up to degree D" becomes a checked, scoped statement.
2. Reproduce the classical landscape: Lehmer's polynomial, Smyth's bound, known small-measure
   Salem numbers.
3. Structure-of-the-frontier survey: Dobrowolski-type bounds, Salem/Pisot connections, and
   what a proof of a uniform gap would need to overcome.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 5

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
