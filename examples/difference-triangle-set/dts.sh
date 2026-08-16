#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — (7,5)-difference triangle sets: scope 111
#
# Construct a (7,5)-DTS with scope <= 111, prove nonexistence with a checkable
# certificate, or produce rigorously verified partial results. A scope-112
# construction is known; 111 is the target. Fully finite and certificate-
# friendly: constructions are verified by two independent validators, and
# nonexistence claims require DRAT/LRAT/SMT certificates — never a bare solver
# exit status. The workflow phases and claim policy are spelled out in the
# problem statement below.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# Optional: z3 on the host PATH enables the SMT verifier (proof_submit smt).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./dts.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set model.timeout_seconds 2400
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted
if command -v z3 >/dev/null 2>&1; then
  opentorus config set tools.verifiers.smt true
fi

# --- 3. Search & verification environment ------------------------------------
# SAT/SMT/CP search plus two independent exact validators in plain Python.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy z3-solver python-sat ortools
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Sources --------------------------------------------------------------
# Deliberately none pre-registered: the primary DTS scope tables live in
# journal/handbook sources (often paywalled). Phase 1 of the statement demands
# a proper status audit via lit_search, with inaccessible metadata marked
# missing — never invented. No --min-papers quota for the same reason.

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: A (7,5)-difference triangle set with scope at most 111

Construct or prove the nonexistence of a (7,5)-difference triangle set with scope at
most 111.

**Definition.** A candidate consists of seven rows
$0 = a_{i,0} < a_{i,1} < \dots < a_{i,5} \le 111$ for $i = 0,\dots,6$. For every row,
form all 15 positive differences $a_{i,j} - a_{i,k}$, $0 \le k < j \le 5$. All 105
differences across all seven rows must be pairwise distinct. A construction with scope
112 is known; the target is scope 111.

**Research objectives.**
1. Construct a valid solution with scope at most 111; or
2. produce a machine-checkable proof that no such construction exists; or
3. derive new necessary conditions, excluded structural classes, improved lower bounds,
   or other rigorously verified partial results.

**Phase 1 — status and specification audit.** Locate the primary sources for the best
known scope-112 construction; confirm that scope 111 remains open; record exact
bibliographic references and publication dates; check whether different sources use
different DTS conventions; write an unambiguous canonical problem specification.

**Phase 2 — independent verification.** Before running any search: implement a minimal
exact validator; implement a second independent validator using a different code path;
add positive, negative, boundary, duplicate-difference and malformed-input tests;
reproduce and verify at least one published scope-112 construction. The search
implementation must not be used as the only verifier.

**Phase 3 — structural analysis.** Investigate normalization and symmetry-breaking
rules; feasible and impossible first rows; distributions of the six unused differences;
parity and modular constraints; difference-sum identities; bounds induced by small and
large differences; canonical ordering of rows; equivalence classes under reflection and
row permutation. Every claimed obstruction must be checked exhaustively or proved.

**Phase 4 — search.** Implement and compare at least three independent approaches:
CP-SAT / constraint programming; SAT or SMT with explicit symmetry breaking; heuristic
search followed by exact completion. Consider incremental solving, assumption literals,
learned nogoods, large-neighborhood search, tabu search, simulated annealing, portfolio
runs with reproducible seeds, and partitioning by canonical first-row classes.

**Phase 5 — rigorous output.**
- For a construction: the seven rows in plain-text canonical format, verified by BOTH
  independent validators; all 105 differences listed; hashes, source code, environment
  and reproduction commands included. Exact re-verification belongs in
  `proof_submit(backend="sympy")` (or `"smt"` if enabled) so the construction becomes a
  verification artifact.
- For nonexistence: a DRAT, LRAT, SMT or equivalent independently checkable certificate;
  all symmetry-breaking constraints documented and shown satisfiability-preserving; the
  certificate verified with an independent checker.
- For partial results: state the excluded class precisely; provide a proof or exhaustive
  certificate; quantify how much of the search space was eliminated; never describe an
  incomplete search as evidence of nonexistence.

**Claim policy.** Classify every conclusion as exactly one of: verified construction;
machine-checked theorem; exhaustive certified result; numerical or computational
evidence; conjecture; failed or inconclusive attempt. A passing heuristic test is not a
proof. A solver exit status without a checkable certificate is not a proof of
nonexistence.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
opentorus --verbose prove "${TARGET}"

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
