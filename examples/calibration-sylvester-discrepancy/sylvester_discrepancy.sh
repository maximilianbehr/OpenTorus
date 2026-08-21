#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — Discrepancy of Sylvester Hadamard matrices
#                                 (a refuted conjecture with an exact, tiny
#                                 counterexample the agent must reconstruct)
#
# KNOWN ground truth (see README.md): Randomstrasse101 Conjecture 13 -
# disc(H_k) = sqrt2 * sqrt(2^k) for the 2^k x 2^k Sylvester Hadamard matrix
# and every odd k - is FALSE for every odd k >= 9 and true only for
# k = 1, 3, 5, 7. Reported in arXiv:2504.20539 (Updates: Buhai, private
# communication 2025, via the connection to Boolean nonlinearity /
# Patterson-Wiedemann 1983); the mechanism is the identity
# disc(H_k) = 2^k - 2 rho(RM(1,k)) with rho the covering radius of the
# first-order Reed-Muller code (max nonlinearity of k-variable Boolean
# functions; (H_k x)_S is a Walsh coefficient). Kavut-Yuecel's 9-variable
# functions with nonlinearity 242 (arXiv:0808.0684) give ||H_9 x||_inf = 28
# < 32 - a 512-point integer Walsh-Hadamard transform certifies it (the
# example-creation audit re-ran it). Residual: 24 <= disc(H_9) <= 28 exactly
# unknown (242 <= rho(RM(1,9)) <= 244).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./sylvester_discrepancy.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Integer fast Walsh-Hadamard transforms (numpy), brute force over sign
# vectors for small k, exact certificates (sympy).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2504.20539
opentorus paper add https://arxiv.org/abs/0808.0684

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Discrepancy of Sylvester Hadamard matrices for odd k — find and verify a refutation

**Setup.** Let $H_0 = [1]$ and $H_k = \begin{bmatrix} H_{k-1} & H_{k-1} \\ H_{k-1} & -H_{k-1}\end{bmatrix}$
be the $2^k \times 2^k$ Sylvester Hadamard matrix, and for a $\pm1$ matrix $A$ let
$\mathrm{disc}(A) = \min_{x \in \{\pm1\}^n} \lVert Ax \rVert_\infty$. Orthogonality gives
$\mathrm{disc}(H_k) \ge \sqrt{2^k}$; for even $k$ equality holds; for odd $k$ the vector
$x^\natural_{(k)} = (1,1,1,-1) \otimes x^\natural_{(k-2)}$ gives $\lVert H_k x^\natural\rVert_\infty =
\sqrt2\sqrt{2^k}$. **Conjecture 13 (Randomstrasse101, Dec 2024):** for odd $k$,
$\mathrm{disc}(H_k) = \sqrt2\sqrt{2^k}$.

**Task for this dossier (disprove mode).** Refute the conjecture by producing, for some odd
$k$, an explicit sign vector $x \in \{\pm1\}^{2^k}$ with $\lVert H_k x\rVert_\infty <
\sqrt2\sqrt{2^k}$, via EITHER route:

1. **Literature route.** Search for the reported refutation and its mechanism: identify a
   $\pm1$ vector of length $2^k$ with a Boolean function $f$ on $k$ variables ($x = (-1)^f$);
   then $(H_k x)_S$ is the Walsh coefficient $W_f(S)$, so
   $\lVert H_k x\rVert_\infty = 2^k - 2\,\mathrm{nl}(f)$ and
   $\mathrm{disc}(H_k) = 2^k - 2\rho(\mathrm{RM}(1,k))$ with $\rho$ the covering radius of the
   first-order Reed–Muller code (the maximum nonlinearity). The conjecture is therefore
   equivalent to $\rho(\mathrm{RM}(1,k)) = 2^{k-1} - 2^{(k-1)/2}$ for odd $k$ — and Boolean
   functions beating that bound are classical for $k = 15$ (Patterson–Wiedemann 1983,
   nonlinearity 16276) and known for $k = 9$ (Kavut–Yücel, nonlinearity 242, truth tables
   published), $k = 11$ and $k = 13$; indeed such functions exist iff $k > 7$. Reconstruct
   a 9-variable nonlinearity-242 function from the parsed source (or search the generalized
   rotation-symmetric class) and certify $\lVert H_9 x\rVert_\infty = 28 < 32$.
2. **Direct search route.** Search $\{\pm1\}^{512}$ directly with local search / simulated
   annealing minimizing $\lVert H_9 x\rVert_\infty$ (fast Walsh–Hadamard transform, integer
   arithmetic); the target is any $x$ with value $\le 30$ (values are $\equiv 0 \bmod 4$
   here, so $28$).

Either way, **verify** the candidate: compute $H_k x$ exactly in integers (fast
Walsh–Hadamard transform, $2^k$ points) and record the maximum absolute entry — a finite,
exact certificate; submit it via proof_submit (sympy backend) and record it through the
proper verification pathway (COUNTEREXAMPLE_VERIFIED needs the explicit vector and its
exact transform, not a citation).

**Report honestly what remains.** The conjecture holds for $k = 1, 3, 5, 7$ (covering radii
$0, 2, 12, 56$; the $k = 7$ value is a theorem — Mykkeltveit 1980, Hou 1996) and fails for
every odd $k \ge 9$; the EXACT values $\mathrm{disc}(H_9) \in \{24, 26, 28\}$
($242 \le \rho(\mathrm{RM}(1,9)) \le 244$), $\mathrm{disc}(H_{11}) \le 56$–$60$,
$\mathrm{disc}(H_{13}) \le 112$–$120$ are open finite problems. The refutation does NOT touch
the neighboring Conjecture 12 ($\limsup_n \sup_A \mathrm{disc}(A)/\sqrt n > 1$), which the
Updates note explicitly leaves open — the $H_k$ family may still serve it.

**Honesty requirements.** The refutation is reported as such only with the exact certificate
in this workspace; the private-communication provenance in the parsed source is stated as
provenance, and the identity/mechanism are attributed correctly (Boolean nonlinearity,
Patterson–Wiedemann; the identity itself is elementary). Metadata not fetchable is marked
missing.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Refutation run ------------------------------------------------------
# `prove` gates on the honesty linter: a report that still overclaims exits non-zero.
# That is a finding to read, not a crash — but under `set -e` it aborted this driver
# right here, before the report/verdict/PDF steps below ever ran. Keep the signal,
# finish the workflow, and exit with it at the end.
PROVE_RC=0
opentorus --verbose prove "${TARGET}" --disprove --min-papers 2 || PROVE_RC=$?

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: an explicit x in {+-1}^512 with ||H_9 x||_inf = 28 < 32,"
echo "certified by an exact integer Walsh-Hadamard transform (COUNTEREXAMPLE_VERIFIED);"
echo "the report states the conjecture holds for k = 1,3,5,7 and fails for all odd k >= 9,"
echo "keeps disc(H_9) in {24,26,28} open, and leaves Conjecture 12 open."

exit "${PROVE_RC}"
