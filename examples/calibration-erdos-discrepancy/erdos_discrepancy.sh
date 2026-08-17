#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — The Erdős discrepancy problem (solved 2015)
#
# KNOWN ground truth (see README.md): PROVED by Tao (arXiv:1509.05363,
# Discrete Analysis 2016:1) via the Polymath5 Fourier reduction and the
# logarithmically averaged two-point Elliott conjecture (arXiv:1509.05422).
# The finite cases are exact SAT results: max length 11 at discrepancy 1;
# max length 1160 at discrepancy 2 (Konev-Lisitsa 2014, arXiv:1402.2184,
# 1161 UNSAT with a ~13 GB DRUP certificate); at discrepancy 3 the exact
# maximum is UNKNOWN (>= 130,000; the 127,645 figure is the exact maximum for
# multiplicative sequences only). This run checks that the agent reports a
# SOLVED problem as solved (not open), reproduces the small finite cases with
# certificates, and keeps the C=3 boundary honest.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./erdos_discrepancy.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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

# --- 3. Numerical experiment environment ------------------------------------
# Exact discrepancy computation (integers), SAT with proof logging for the
# small finite cases.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/1509.05363
opentorus paper add https://arxiv.org/abs/1402.2184
opentorus paper add https://arxiv.org/abs/1405.3097

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Erdős discrepancy problem — determine the current status

**Setup.** For a sequence $x_1, x_2, \dots \in \{-1, +1\}$ and $C > 0$, Erdős asked
(1930s): must there exist $d, k$ with
$$\left|\sum_{i=1}^{k} x_{id}\right| > C\,?$$
Equivalently: is the discrepancy $\sup_{d,k} |\sum_{i \le k} x_{id}|$ of every
$\pm 1$ sequence infinite?

**Task for this dossier.** Determine the *current* status in the literature — including
who proved what, where it is published, and which finite quantitative questions remain
open — and corroborate the finite cases with certified computations:

1. **Status.** Establish from parsed sources whether the problem is open or solved, by
   whom, and with what proof infrastructure; distinguish the roles of the Polymath5
   project (reductions, records) and of the final proof. Note any quantitative follow-up
   (growth-rate questions) that remains open.
2. **Finite case C = 1.** Determine the exact maximal length of a $\pm 1$ sequence with
   discrepancy $\le 1$ by exhaustive computation or SAT, with the boundary case
   certified (UNSAT at length L+1).
3. **Finite case C = 2.** Reproduce the SAT result: find a discrepancy-2 sequence of
   length 1160 (SAT — feasible in minutes on modern hardware) and record honestly that
   the 1161 impossibility is a known published result whose original certificate was
   ~13 GB — reproduce it only if budget allows, otherwise cite it as a KNOWN_RESULT
   without claiming to have re-verified it.
4. **Boundary honesty at C = 3.** The exact maximum is UNKNOWN; sequences of length
   > 130,000 exist, and the exact value 127,645 applies to (completely) multiplicative
   sequences only. The report must not conflate the two.

**Honesty requirements.** "Solved" is claimed only with the published proof cited from a
local PAPER-* artifact; SAT experiments *support* the finite statements and are
themselves theorem-grade only where a certificate was produced and checked in this
workspace. Attributions (Polymath5 vs. Tao vs. Konev–Lisitsa) must match the parsed
sources; quantitative open questions are labelled open.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + certified numerics ------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 3

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: the report must state the problem is SOLVED (Tao 2015/16,"
echo "Discrete Analysis) with Polymath5 credited for the reduction, reproduce C=1"
echo "(max length 11) with an UNSAT certificate at 12, find a length-1160"
echo "discrepancy-2 sequence, and keep the C=3 exact maximum honestly open"
echo "(127,645 is the multiplicative case, not the general one)."
