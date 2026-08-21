#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — The ellipsoid fitting conjecture
#                                 (a claimed proof one week old)
#
# KNOWN ground truth (see README.md): the sharp n ~ d^2/4 threshold
# (Saunderson-Chandrasekaran-Parrilo-Willsky 2012; Randomstrasse101
# Conjecture 6) was CLAIMED PROVED on 2026-08-10 by Misiakiewicz-Wen
# (arXiv:2608.10184, unrefereed, no public reaction at audit time). The
# established layer: fits exist for n <= d^2/C (three independent 2023
# proofs) and the sharp 1/4 threshold holds for APPROXIMATE fitting with
# bounded spectrum (Bandeira-Maillard, EJP 2025). This run tests whether the
# agent labels a days-old preprint as "claimed" (not "open", not "proved"),
# keeps the theorem layer separate, and treats its own SDP experiments at the
# 1/4 threshold as support only.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./ellipsoid_fitting.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# SDP feasibility (cvxpy + Clarabel/SCS), exact rational certificates (sympy).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy cvxpy clarabel
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2608.10184
opentorus paper add https://arxiv.org/abs/2310.05787
opentorus paper add https://arxiv.org/abs/2307.01181

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The ellipsoid fitting conjecture — determine the current status

**Setup.** Let $x_1, \dots, x_n \sim \mathcal N(0, I_d/d)$ be i.i.d. An *ellipsoid fit* is a
centered ellipsoid $\{x : x^\top S x = 1\}$, $S \succeq 0$, passing through every $x_i$ —
equivalently the SDP feasibility problem $\exists S \succeq 0 : x_i^\top S x_i = 1\ \forall i$
(covariance $I_d/d$ is a normalization; other authors write $\mathcal N(0, I_d)$ with
$x_i^\top S x_i = d$, which is the same problem after rescaling). **Conjecture** (Saunderson
et al. 2012; Randomstrasse101 Conjecture 6): for every $\varepsilon > 0$,
$\limsup_{d\to\infty} n/d^2 \le (1-\varepsilon)/4$ implies a fit exists with probability
$\to 1$, and $\liminf n/d^2 \ge (1+\varepsilon)/4$ implies no fit with probability $\to 1$.

**Task for this dossier.** Determine the *current* status in the literature and produce an
honest status sketch that separates three layers:

1. **The theorem layer.** Fits exist for $n \le d^2/C$ (three independent 2023 proofs:
   Hsieh–Kothari–Potechin–Xu; Tulsiani–Wu; Bandeira–Maillard–Mendelson–Paquette,
   arXiv:2307.01181), after $d^2/\mathrm{polylog}$ (Potechin–Turner–Venkat–Wein;
   Kane–Diakonikolas); the sharp $1/4$ threshold for *approximate* fitting with bounded
   spectrum, and the impossibility of small error above $1/4$ unless the shortest axis
   degenerates (Bandeira–Maillard, arXiv:2310.05787, EJP 2025); the trivial upper bound
   $n \lesssim d^2/2$ (dimension count); the replica prediction of $1/4$ (Maillard–Kunisky).
2. **The claim layer.** A very recent preprint (arXiv:2608.10184, submitted 2026-08-10)
   claims the full conjecture: a fit exists whp below $1/4$ (and, as an additional
   guarantee, with spectrum in a fixed interval $[\lambda_-, \lambda_+] \subset (0,\infty)$),
   and no fit exists whp above $1/4$ without any spectral restriction. Report it as a
   claimed proof under review — days old, unrefereed, no independent confirmation — never
   as an established theorem and never as "still open" without naming it.
3. **The numerical layer (support only).** Sample $x_i$, solve the SDP feasibility for
   $d \in [10, 50]$ and $n$ around $d^2/4$; estimate the empirical transition and its
   finite-size drift; test the least-squares / minimum-nuclear-norm / minimum-Frobenius
   candidates $S^\star$ (replica prediction: min-nuclear-norm succeeds through the SAT
   phase, min-Frobenius fails below $1/4$); watch the shortest axis near threshold. For a
   fixed rational sample a feasible $S$ is certifiable exactly (rational $S \succeq 0$ via
   $LDL^\top$ after projecting onto the affine constraints) and infeasibility via an exact
   Farkas/dual certificate — submit such single-instance certificates via proof_submit.

**Honesty requirements.** Finite-$d$ experiments never decide a limit statement; the
conjecture's status comes only from the literature, with "claimed" and "proved" kept
distinct. Normalizations must be reconciled explicitly when comparing sources. Cite only
locally parsed PAPER-* artifacts.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + numerics ---------------------------------------------------
# `prove` gates on the honesty linter: a report that still overclaims exits non-zero.
# That is a finding to read, not a crash — but under `set -e` it aborted this driver
# right here, before the report/verdict/PDF steps below ever ran. Keep the signal,
# finish the workflow, and exit with it at the end.
PROVE_RC=0
opentorus --verbose prove "${TARGET}" --min-papers 3 || PROVE_RC=$?

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: the report must surface the 2026-08-10 preprint (arXiv:2608.10184)"
echo "and label it claimed/under review, keep the 2023 constant-factor theorems and the"
echo "EJP 2025 approximate-sharp theorem as the established layer, and keep SDP experiments"
echo "at n ~ d^2/4 support-only (single-instance certificates aside)."

exit "${PROVE_RC}"
