#!/usr/bin/env bash
# OpenTorus workflow for open problems from
# "Linear Systems and Eigenvalue Problems: Open Questions from a Simons Workshop"
# (arXiv:2602.05394).
#
# Five small-dimensional, numerically explorable problems (the Forsythe conjecture, Problem
# 2.20, was excluded as too hard). See notes.md for the verbatim statements:
#   3.5  Conditioning of Ritz values from random Krylov subspaces   (counterexample search)
#   2.4  CG vs randomized coordinate descent for lambda_i = i^{-p}  (scaling law)
#   2.13 Eigenvalue clustering vs GMRES iteration counts            (construct + counterexample)
#   3.4  When do Ritz values approximate invariant-subspace eigenvalues (empirical conditions)
#   3.2  Deterministic diagonal perturbation giving an eigenvalue gap   (constructive search)
#
# This script SETS UP the dossiers and then lets OpenTorus tackle one. The agent writes and
# runs its own experiments via exp_run; scripts/test_ritz_conditioning.py is a seed for 3.5.
#
# Usage:  ./simons_open_problems.sh [PROBLEM-ID]
#   PROBLEM-ID defaults to PROBLEM-0001. Run 'opentorus problem list' (printed below) to see
#   which extracted dossier corresponds to which workshop problem, then re-run with that id.
set -e

TARGET="${1:-PROBLEM-0001}"

# Activate your OpenTorus environment (the venv/conda where you installed it) and ensure `opentorus` is on PATH.

# --- Fresh workspace -------------------------------------------------------------------
rm -rf .opentorus
opentorus init

opentorus config set model.provider ollama
opentorus config set model.name gpt-oss:120b
opentorus config set model.base_url http://localhost:11435
opentorus config set model.timeout_seconds 600
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set permissions.mode trusted

# --- Numerics environment (small SPD / non-normal / tridiagonal matrix experiments) ----
mkdir -p docker
cat > docker/Dockerfile << 'EOF'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
EOF
opentorus env prepare python-sci --file docker/Dockerfile

# --- Source paper ----------------------------------------------------------------------
echo "==> Source paper (Simons workshop open problems)"
opentorus paper add https://arxiv.org/abs/2602.05394

# --- Create dossiers from the five curated problems ------------------------------------
echo "==> Dossiers from curated notes (5 problems)"
opentorus problem new --from-markdown notes.md
opentorus problem list

# --- Let OpenTorus tackle one problem --------------------------------------------------
# The prove loop reads the dossier + local papers, may write/run experiments via exp_run,
# records claims/evidence/attempts, and stops honestly: numerical evidence supports or refutes
# but never proves; a verified claim requires a verification artifact.
echo "==> Literature + proof/disproof attempt on ${TARGET}"
opentorus --verbose prove "${TARGET}"

# --- Honest report + PDF ---------------------------------------------------------------
echo "==> Report"
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. Inspect:"
echo "  opentorus problem list                              (all extracted problems)"
echo "  .opentorus/problems/${TARGET}/report.md             (honest report)"
echo
echo "To attack another problem, re-run with its id, e.g.:"
echo "  ./simons_open_problems.sh PROBLEM-0002"
