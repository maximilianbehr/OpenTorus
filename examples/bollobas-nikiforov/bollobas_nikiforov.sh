#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — The Bollobás–Nikiforov conjecture
# Sources: "Bollobás-Nikiforov Conjecture for graphs with not so many
#          triangles", arXiv:2407.19341; "Bollobás-Nikiforov conjecture holds
#          asymptotically almost surely", arXiv:2501.07137; "The Conjecture for
#          Complete Multipartite Graphs and Dense K4-Free Graphs", arXiv:2603.26379.
#
# Conjecture (Bollobás–Nikiforov 2007). For every graph G != K_n with m edges,
# clique number w = w(G), and adjacency eigenvalues l_1 >= l_2 >= ...:
#   l_1^2 + l_2^2  <=  2m (1 - 1/w).
# Known: triangle-free, regular, weakly perfect, Kneser, complete multipartite,
# dense K4-free, and a.a.s. for random graphs. OPEN in general.
#
# A candidate violation is one finite graph — eigenvalues and clique number are
# exactly recomputable, so refutation candidates are machine-checkable.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./bollobas_nikiforov.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Graph-space search: exhaustive small n, simulated annealing / local moves on
# larger n maximizing (l1^2 + l2^2) / (2m(1 - 1/w)); exact re-checks via sympy.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers -------------------------------------------------------
opentorus paper add https://arxiv.org/abs/2407.19341
opentorus paper add https://arxiv.org/abs/2501.07137
opentorus paper add https://arxiv.org/abs/2603.26379

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Bollobás–Nikiforov conjecture

**Source.** B. Bollobás, V. Nikiforov, *Cliques and the spectral radius*,
J. Combin. Theory Ser. B 97 (2007). Recent progress:
[arXiv:2407.19341](https://arxiv.org/abs/2407.19341),
[arXiv:2501.07137](https://arxiv.org/abs/2501.07137),
[arXiv:2603.26379](https://arxiv.org/abs/2603.26379).

**Conjecture.** For every graph $G \ne K_n$ with $m$ edges, clique number $\omega = \omega(G)$,
and adjacency eigenvalues $\lambda_1 \ge \lambda_2 \ge \dots$:
$$
\lambda_1^2 + \lambda_2^2 \;\le\; 2m\Bigl(1 - \frac{1}{\omega}\Bigr).
$$
It strengthens both the spectral Turán bound $\lambda_1^2 \le 2m(1-1/\omega)$ (Nikiforov)
and, morally, Turán-type edge bounds.

**Known.**
- True for triangle-free graphs (Lin–Ning–Wu 2021), regular graphs, weakly perfect graphs,
  Kneser graphs, and graphs with "not so many triangles" (arXiv:2407.19341).
- True for complete multipartite graphs, and for dense $K_4$-free graphs near the Turán
  extremal (arXiv:2603.26379).
- Holds asymptotically almost surely for random graphs (arXiv:2501.07137).

**Open.** The general case.

**Numerically explorable.**
1. Exhaustive check for all graphs up to ~10 vertices (isomorph-free generation), recording
   the extremal ratio $(\lambda_1^2+\lambda_2^2)/(2m(1-1/\omega))$ and the tight families.
2. Guided search at larger $n$: local edge flips / simulated annealing maximizing the ratio,
   seeded with known near-extremal families.
3. Any candidate violation is one finite graph: recompute $\lambda_1, \lambda_2$ exactly
   (characteristic polynomial over $\mathbb{Z}$, isolated with certified enclosures) and
   $\omega$ exactly; submit the arithmetic via `proof_submit` (sympy or interval) so a
   refutation would rest on a verification artifact, not floating-point eigenvalues.
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
