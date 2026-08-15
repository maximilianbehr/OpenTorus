#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — The Marcus–de Oliveira determinantal conjecture
# Source: "A class of normal dilation matrices affirming the Marcus-de Oliveira
#          conjecture", arXiv:2006.14846; surveys: Bebiano et al.;
#          "Revisiting the Marcus–de Oliveira Conjecture", Mathematics 13(5):711, 2025.
#
# Conjecture (Marcus 1972 / de Oliveira 1982). For normal A, B in C^{n x n}
# with eigenvalues a_1..a_n and b_1..b_n,
#   det(A + B)  lies in  conv{ prod_i (a_i + b_sigma(i)) : sigma in S_n }.
# Known for n <= 3 and for essentially Hermitian matrices; OPEN in general —
# even the n = 4 subcase with A Hermitian, B normal is open.
#
# Standard example workflow; a designated counterexample-verification target:
# a violation is one unitary U with det(A + U B U*) outside a hull of n! points,
# checkable in exact/interval arithmetic (LP separating-hyperplane certificate).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./marcus_de_oliveira.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Haar-random and gradient-guided search over U(n); convex-hull membership of
# det(A + U B U*) among the n! products via linear programming.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
opentorus paper add https://arxiv.org/abs/2006.14846

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Marcus–de Oliveira determinantal conjecture

**Source.** M. Marcus (1972), G. N. de Oliveira (1982). Recent affirmative special cases:
[arXiv:2006.14846](https://arxiv.org/abs/2006.14846); survey: *Revisiting the
Marcus–de Oliveira Conjecture*, Mathematics 13(5):711 (2025).

**Setup.** Let $A, B \in \mathbb{C}^{n\times n}$ be normal with eigenvalues
$a_1,\dots,a_n$ and $b_1,\dots,b_n$. As $U$ ranges over the unitary group,
$\det(A + UBU^*)$ traces a region $\Delta(A,B) \subseteq \mathbb{C}$.

**Conjecture (Marcus–de Oliveira).**
$$
\Delta(A,B) \;\subseteq\; \operatorname{conv}\Bigl\{ \prod_{i=1}^n \bigl(a_i + b_{\sigma(i)}\bigr)
\;:\; \sigma \in S_n \Bigr\}.
$$

**Known.**
- True for $n \le 3$; true when $A, B$ are essentially Hermitian; true for the normal
  dilation classes of arXiv:2006.14846; the "external vertices" weak form holds for $n \le 4$.
- **Open in general for every $n \ge 4$** — even the subcase $n = 4$, $A$ Hermitian,
  $B$ normal, is open after 50+ years.

**Open tasks for this dossier.**
1. Survey the frontier: which $(A,B)$ classes are settled, which remain open, and what do
   the known proofs use (Schur–Horn-type majorization, bilinear cones, dilations)?
2. Counterexample search: for random and structured normal pairs, maximize the distance of
   $\det(A + UBU^*)$ from the hull of the $n!$ products over $U \in U(n)$.
3. Certify any candidate violation exactly: the hull is a polygon in $\mathbb{C}\cong\mathbb{R}^2$,
   so non-membership has a linear separating-functional certificate checkable in rational
   or interval arithmetic (`proof_submit(backend="interval")` / sympy).

**Numerically explorable.** For $n \in \{4,5\}$ the $n!$ hull vertices are cheap; membership
is a tiny LP. The search over $U(n)$ is smooth nonconvex optimization (Cayley or exponential
parametrization) — multi-start ascent on hull-distance. A genuine violation would refute the
conjecture with a single machine-checkable witness; absence of violations across large sweeps
is support-only evidence.
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
