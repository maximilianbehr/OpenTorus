#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — The Matrix Spencer conjecture
# Sources: Bansal, Jiang, Meka, "Resolving Matrix Spencer Conjecture Up to
#          Poly-logarithmic Rank", STOC 2023. arXiv:2208.11286.
#          Bandeira et al., "Randomstrasse101: Open Problems of 2024",
#          arXiv:2504.20539 (contains the conjecture's current status).
#
# Conjecture (Zouzias / folklore, "Matrix Spencer"). There is a universal C
# such that for all n and all symmetric A_1..A_n in R^{n x n} with ||A_i|| <= 1
# there exist signs eps_i in {+-1} with || sum_i eps_i A_i || <= C sqrt(n).
# Scalar case: Spencer 1985 ("six standard deviations"). Known when every A_i
# has rank at most n/log^3 n (Bansal-Jiang-Meka 2023); OPEN in general.
#
# Standard example workflow: fresh workspace -> config -> python-sci container
# -> source papers -> dossier -> `opentorus prove` -> honesty-linted report.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./matrix_spencer.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Random low-rank / block instances, exhaustive sign search for small n,
# semidefinite relaxations of the sign optimum.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers -------------------------------------------------------
opentorus paper add https://arxiv.org/abs/2208.11286
opentorus paper add https://arxiv.org/abs/2504.20539

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Matrix Spencer conjecture

**Source.** N. Bansal, H. Jiang, R. Meka,
[arXiv:2208.11286](https://arxiv.org/abs/2208.11286) (STOC 2023); status survey in
*Randomstrasse101: Open Problems of 2024*, [arXiv:2504.20539](https://arxiv.org/abs/2504.20539).

**Conjecture (Matrix Spencer).** There exists a universal constant $C$ such that for every
$n$ and all symmetric matrices $A_1,\dots,A_n \in \mathbb{R}^{n\times n}$ with
$\lVert A_i\rVert \le 1$ (spectral norm), there are signs $\varepsilon \in \{\pm 1\}^n$ with
$$
\Bigl\lVert \sum_{i=1}^n \varepsilon_i A_i \Bigr\rVert \;\le\; C\sqrt{n}.
$$

**Known.**
- Scalar case (diagonal $A_i$): Spencer's six-standard-deviations theorem (1985).
- Random signs give $O(\sqrt{n \log n})$ (matrix Khintchine / noncommutative concentration);
  the conjecture asks to remove the $\sqrt{\log n}$ via *chosen* signs.
- **True when every $A_i$ has rank at most $n/\log^3 n$** (Bansal–Jiang–Meka 2023), via
  partial coloring and sharp matrix concentration.
- Average-case variants and group-representation variants are active (see the
  Randomstrasse101 status entry).

**Open.** The general (full-rank) case. Either prove the $C\sqrt{n}$ bound for all inputs,
or exhibit matrices $A_1,\dots,A_n$ for which every sign choice has
$\lVert\sum_i \varepsilon_i A_i\rVert = \omega(\sqrt{n})$ — which would refute the conjecture.

**Numerically explorable.** For small $n$ the sign optimum
$\min_\varepsilon \lVert\sum_i \varepsilon_i A_i\rVert$ is computable exactly (exhaustive over
$2^{n-1}$ sign patterns); compare against $\sqrt{n}$ across structured families (low rank,
block, Gaussian, adversarial gradient-crafted). Any conjectured-violation candidate is a
finite object: a fixed family plus an exhaustively-verified sign minimum — checkable in
exact arithmetic via sympy.
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
