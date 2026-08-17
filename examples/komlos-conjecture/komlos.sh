#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — The Komlós conjecture (vector balancing)
# Source: Dadush, Garg, Lovett, Nikolov, "Towards a Constructive Version of
#         Banaszczyk's Vector Balancing Theorem", arXiv:1612.04304.
#
# Conjecture (Komlós). There is a universal constant K such that for every d,
# every n, and all v_1..v_n in R^d with ||v_i||_2 <= 1 there exist signs
# eps_i in {+-1} with || sum_i eps_i v_i ||_inf <= K.
# Best known upper bound: O~(log^{1/4} n) (Bansal-Jiang, arXiv:2508.03961,
# Aug 2025 - improving Banaszczyk's O(sqrt(log n)) of 1998); best lower bound
# K >= 1 + sqrt(2) (Kunisky, arXiv:2111.02974). Implies the Beck-Fiala
# conjecture. OPEN (re-checked 2026-08-17) - no universal constant, no
# counterexample.
#
# Small cases are exactly decidable: for fixed (n, d) and rational vectors the
# sign minimum is exhaustive or SMT-encodable — certificates, not anecdotes.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# Optional: z3 on the host PATH enables the SMT verifier (proof_submit smt).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./komlos.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
if command -v z3 >/dev/null 2>&1; then
  opentorus config set tools.verifiers.smt true
fi

# --- 3. Numerical experiment environment ------------------------------------
# Instance search (worst-case families raising the sign minimum), exhaustive
# sign minima for small n, SMT encodings, greedy/Banaszczyk-style rounding.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy z3-solver
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
opentorus paper add https://arxiv.org/abs/1612.04304
opentorus paper add https://arxiv.org/abs/2508.03961
opentorus paper add https://arxiv.org/abs/2111.02974

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Komlós conjecture

**Source.** Attributed to J. Komlós (1980s, unpublished). Constructive state of the art:
D. Dadush, S. Garg, S. Lovett, A. Nikolov,
[arXiv:1612.04304](https://arxiv.org/abs/1612.04304).

**Conjecture (Komlós).** There exists a universal constant $K$ such that for every
dimension $d$, every $n$, and all vectors $v_1,\dots,v_n \in \mathbb{R}^d$ with
$\lVert v_i\rVert_2 \le 1$, there are signs $\varepsilon \in \{\pm 1\}^n$ with
$$
\Bigl\lVert \sum_{i=1}^n \varepsilon_i v_i \Bigr\rVert_\infty \;\le\; K.
$$

**Known.**
- Banaszczyk (1998): $K = O(\sqrt{\log n})$, made constructive by Dadush–Garg–Lovett–Nikolov
  and follow-ups; improved to $\tilde O(\log^{1/4} n)$ by Bansal–Jiang
  ([arXiv:2508.03961](https://arxiv.org/abs/2508.03961), Aug 2025 — the current best
  upper bound, which also settles Beck–Fiala for $t \ge \log^2 n$).
- The conjecture implies the Beck–Fiala conjecture ($O(\sqrt{t})$ discrepancy for
  $t$-sparse set systems) via scaling columns of incidence matrices.
- Lower bounds: $K \ge 1 + \sqrt 2$ (Kunisky, [arXiv:2111.02974](https://arxiv.org/abs/2111.02974),
  via scaled clause–variable matrices of unsatisfiable formulas — a limit of a family, not a
  single small matrix); no sequence of instances with unbounded sign minimum is known.

**Open.** Prove a universal $K$, or exhibit instances with sign minimum $\to \infty$
(refutation).

**Numerically explorable.**
1. For fixed small $(n,d)$ and rational vectors, the sign minimum
   $\min_\varepsilon \lVert\sum_i \varepsilon_i v_i\rVert_\infty$ is exactly computable
   (exhaustion over $2^{n-1}$; or SMT: the assertion "every sign choice exceeds $c$" is a
   universally-quantified statement whose negation is a finite disjunction — z3-checkable).
2. Search for hard instances: gradient/evolutionary search over unit vectors maximizing the
   exact sign minimum; track the record as a function of $n$.
3. Certified records become verification artifacts: a rational instance + exhaustive minimum
   submitted via `proof_submit(backend="sympy")` (or "smt" when z3 is enabled).

Bounded records for bounded $n$ can never prove the conjecture; a genuinely growing certified
record sequence would be evidence toward refutation — and only an unbounded proof refutes.
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
