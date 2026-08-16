#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — The growth factor of complete pivoting (Wilkinson 1961)
# Sources: Edelman, Urschel, "Some New Results on the Maximum Growth Factor in
#          Gaussian Elimination", SIMAX 45(2), 2024. arXiv:2303.04892.
#          Bisain, Edelman, Urschel, "A New Upper Bound for the Growth Factor in
#          Gaussian Elimination with Complete Pivoting", 2024. arXiv:2312.00994.
#
# Open problem. Let g(n) be the maximum growth factor of Gaussian elimination
# with complete pivoting over all real nonsingular n x n matrices. Is g(n)
# polynomial in n? Exact values are known only for n <= 4; even g(5) is open.
# Best upper bound: n^(0.2079 ln n + 0.91) (arXiv:2312.00994) — the first
# improvement on Wilkinson's 1961 bound in over sixty years.
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. build the python-sci container for growth-factor optimization sweeps
#   4. register the source papers as local PAPER-* artifacts
#   5. write the problem statement to notes.md and create the dossier
#   6. run `opentorus prove` (literature -> proof draft -> gap-fill)
#   7. build an honesty-linted report and export a PDF
#
# The interval verifier is enabled by default, so the agent can certify a
# candidate growth lower bound rigorously via proof_submit(backend="interval").
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./gecp_growth_factor.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# The draft/gap-fill no-progress backstops still end a stuck run.
opentorus config set permissions.mode trusted

# --- 3. Numerical experiment environment ------------------------------------
# Local optimization over matrices (projected gradient / multi-start) hunting
# large growth, exact rational re-checks, and interval certification.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers -------------------------------------------------------
opentorus paper add https://arxiv.org/abs/2303.04892
opentorus paper add https://arxiv.org/abs/2312.00994

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Is the maximum growth factor of complete pivoting polynomial in n?

**Source.** J. H. Wilkinson, *Error analysis of direct methods of matrix inversion*,
J. ACM 8 (1961). Modern status: A. Edelman, J. Urschel,
[arXiv:2303.04892](https://arxiv.org/abs/2303.04892) (SIMAX 2024); A. Bisain, A. Edelman,
J. Urschel, [arXiv:2312.00994](https://arxiv.org/abs/2312.00994) (2024).

**Setup.** For a nonsingular $A \in \mathbb{R}^{n\times n}$, run Gaussian elimination with
complete pivoting and let $A^{(k)}$ be the $k$-th intermediate matrix. The growth factor is
$$
g(A) \;=\; \frac{\max_{i,j,k} |a^{(k)}_{ij}|}{\max_{i,j} |a_{ij}|},
\qquad
g(n) \;=\; \sup_{A} g(A).
$$

**Open problem.** Determine the asymptotic behaviour of $g(n)$: is $g(n) = O(n^{C})$ for some
constant $C$, or superpolynomial? Determine $g(5)$.

**Known.**
- $g(1)=1$, $g(2)=2$, $g(3)=2.25$, $g(4)=4$; **no exact value is known for any $n \ge 5$**.
- Upper bound: $g(n) \le n^{\,0.2079\ln n + 0.91}$ (Bisain–Edelman–Urschel 2024), improving
  Wilkinson's 1961 quasi-polynomial bound for the first time in six decades.
- Cryer's 1968 conjecture $g(n) \le n$ (equality iff Hadamard) is **false**: growth $> 13$
  occurs for $n = 13$ (Gould 1991, floating point; verified in exact arithmetic by Edelman).
- Numerical optimization (Edelman–Urschel 2024) gives certified-quality lower bounds for
  $n \le 100$, suggests $g(n) > n$ exactly for $n \ge 11$, and gives $g(100) > 3n$.

**Open subquestions for this dossier.**
1. Improve the lower bound for a concrete small $n$ (e.g. $n = 5$): find $A$ with $g(A)$
   exceeding the best published value, certified in exact/interval arithmetic.
2. Polynomial vs. superpolynomial growth of $g(n)$.
3. The threshold conjecture: $g(n) > n \iff n \ge 11$.

**Numerically explorable.** Growth maximization is a smooth nonconvex optimization over
matrices (multi-start projected gradient on the pivot-ordered elimination); any candidate
record matrix is a *finite certificate*: re-run elimination in rational or interval
arithmetic and submit the certified enclosure via the interval verifier
(`proof_submit(backend="interval")`) so the lower bound becomes a verification artifact,
not merely a floating-point observation.
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
