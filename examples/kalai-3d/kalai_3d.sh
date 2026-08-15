#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Kalai's 3^d conjecture (centrally symmetric polytopes)
# Source: Sanyal, Werner, Ziegler, "On Kalai's conjectures concerning centrally
#         symmetric polytopes", arXiv:0708.3661.
#
# Conjecture (Kalai 1989, "3^d"). Every centrally symmetric d-dimensional
# polytope has at least 3^d nonempty faces (vertices, edges, ..., the polytope
# itself). Hanner polytopes attain exactly 3^d. Proved for d <= 4
# (Sanyal-Werner-Ziegler 2009, who also refuted Kalai's stronger conjectures
# B and C); OPEN for every d >= 5 (3^5 = 243).
#
# Face counting for concrete polytopes is exact combinatorics — candidate
# near-minimizers are finite certificates.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./kalai_3d.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact face-lattice computation for concrete cs polytopes (V/H representation
# via scipy ConvexHull + exact rational re-checks with sympy/fractions),
# searches over Hanner-adjacent constructions in d = 5.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
opentorus paper add https://arxiv.org/abs/0708.3661

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Kalai's 3^d conjecture for centrally symmetric polytopes

**Source.** G. Kalai, *The number of faces of centrally-symmetric polytopes*,
Graphs Combin. 5 (1989). Status: R. Sanyal, A. Werner, G. M. Ziegler,
[arXiv:0708.3661](https://arxiv.org/abs/0708.3661) (Discrete Comput. Geom. 2009).

**Conjecture (3^d).** Every centrally symmetric ($P = -P$) $d$-dimensional convex polytope
has at least $3^d$ nonempty faces, counting faces of all dimensions $0,\dots,d$ (i.e.
$s(P) = \sum_{k=0}^{d} f_{k}(P) \ge 3^d$, with $f_d = 1$ for $P$ itself).

**Known.**
- Hanner polytopes (iterated products and free sums starting from segments) attain $s(P) = 3^d$
  exactly; the conjecture says they are minimizers.
- **True for $d \le 4$** (Sanyal–Werner–Ziegler 2009). The same paper *refuted* Kalai's
  stronger conjectures B (flag-number domination) and C for $d \ge 4$ — a caution that the
  plausible strengthenings of this circle of ideas fail.
- Related: the conjecture is connected to Mahler's volume conjecture (same conjectured
  extremizers) — a suggestive but unproven analogy.

**Open.** Every $d \ge 5$; the first open case asks whether a centrally symmetric 5-polytope
can have fewer than $3^5 = 243$ nonempty faces.

**Numerically explorable.**
1. Exact face counting: for concrete cs polytopes given by vertices, the face lattice is
   finite combinatorics; compute $s(P)$ exactly (rational arithmetic, no rounding).
2. Search in $d = 5$: perturbations, products/free sums, and Minkowski-type combinations of
   Hanner and non-Hanner seeds, hunting $s(P) < 243$.
3. Any candidate violation is a finite certificate — a vertex list whose face lattice must be
   recomputed exactly (sympy over the rationals; `proof_submit(backend="sympy")` for the
   arithmetic identities involved). Sweeps that find nothing are support only.
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
