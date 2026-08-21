#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Best polynomial approximation of the matrix sign function
# Source: arXiv:2504.01500
#
# The minimax error of degree-2^m-computable polynomials approximating sign(x)
# on [-1,-delta] u [delta,1]. The agent attacks it with literature + numerics.
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. build the python-sci container for the approximation experiments
#   4. register the source paper as a local PAPER-* artifact
#   5. write the problem statement to notes.md and create the dossier
#   6. run `opentorus prove` (literature -> proof draft -> gap-fill)
#   7. build an honesty-linted report and export a PDF
#
# Prerequisites:
#   - `opentorus` on PATH (activate the env where you installed it)
#   - Docker, for the python-sci container
#   - a tool-calling model; this script targets a local Ollama server on :11434 (override with OPENTORUS_MODEL / OPENTORUS_BASE_URL)
#
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./sign.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# Activate the env where you installed OpenTorus so `opentorus` is on PATH, e.g.:
#   source ~/GITHUB/OpenTorus/.venv/bin/activate

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
# Edit these for your provider/model. Defaults: a local Ollama model on :11434 (override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
opentorus config set model.provider "${OPENTORUS_PROVIDER:-ollama}"
opentorus config set model.name "${OPENTORUS_MODEL:-gemma4:31b}"              # or: gemma4:31b, gpt-4o-mini, …
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
opentorus config set model.timeout_seconds 1200         # raise for large local models
opentorus config set agent.style autonomous            # fewer prompts; destructive ops still confirmed
opentorus config set agent.max_steps inf               # no overall step cap (Ctrl-C to stop)
opentorus config set agent.prove_gap_fill_max_steps inf  # no separate gap-fill cap
opentorus config set permissions.mode trusted          # auto-allow low/medium-risk actions

# --- 3. Numerical experiment environment ------------------------------------
# Experiments run in a pinned container; build a small scientific-Python image.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
# Register the paper as a local PAPER-* artifact (reports cite only local sources).
opentorus paper add https://arxiv.org/abs/2504.01500

# --- 5. Problem statement & dossier -----------------------------------------
# Quote 'NOTES' so the shell does not expand the LaTeX math ($$, $m$, $\delta$, …).
cat > notes.md << 'NOTES'
# Problem: Best polynomial approximation of the matrix sign function

Let $\Pi_{2^m}^*$ be the set of univariate polynomials whose corresponding matrix function
can be computed with $m$ matrix-matrix multiplications and an arbitrary number of matrix
additions and scalings. We consider the problem of determining the best such polynomial
that approximates the sign function in

$$
I := [-1,-\delta] \cup [\delta,1],
$$

$$
\varepsilon_m^* =
\min_{p \in \Pi_{2^m}^*}
\max_{x \in I}
|p(x) - \operatorname{sign}(x)|.
$$

What is the asymptotic error $\varepsilon_m^*$ as a function of $m$ and $\delta$?

**Machine-checkable pieces.** The asymptotic rate itself is not a certificate question, but
the algebra underneath it is exact and belongs in the verifier:
- one Newton or Halley step written out as an identity in the iterate — e.g.
  $x_{k+1} = \tfrac12(x_k + x_k^{-1})$ satisfies $x_{k+1}^2 - 1 = \tfrac{(x_k^2-1)^2}{4x_k^2}$ —
  submitted symbolically via `proof_submit(backend="sympy")`;
- the exact error of a *specific* small-degree minimax polynomial on a named interval, as a
  closed arithmetic check or an `interval` enclosure;
- any identity a lemma reduces to.

Only an ACCEPTED `proof_submit` is machine-checked; `exp_run` results are evidence, not
proof. Do NOT manufacture a certificate for the asymptotic question — record it as `[GAP-n]`.
NOTES
# `--structured` maps the single top-level '# ' heading to one dossier (PROBLEM-0001).
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
# The prove loop reads the dossier + local papers, may write/run experiments via
# exp_run, and records claims/evidence/attempts. Numerical evidence only *supports*
# a claim; a verified claim requires a verification artifact. --min-papers gates
# proof drafting on gathering at least N local papers first.
# `prove` gates on the honesty linter: a report that still overclaims exits non-zero.
# That is a finding to read, not a crash — but under `set -e` it aborted this driver
# right here, before the report/verdict/PDF steps below ever ran. Keep the signal,
# finish the workflow, and exit with it at the end.
PROVE_RC=0
opentorus --verbose prove "${TARGET}" --min-papers 10 || PROVE_RC=$?

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"

exit "${PROVE_RC}"
