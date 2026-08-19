#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Balan–Wang stability conjecture for
#                              real phase retrieval at N = 2M-1
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: Randomstrasse101 open-problems blog (ETH Zurich), "Injectivity and
#         Stability of Phase Retrieval (problems 19-21)", A. S. Bandeira,
#         2025-06-04; https://randomstrasse101.math.ethz.ch/posts/StablePhaseRetrieval/
#         Archived as arXiv:2603.29571 (Open Problems of 2025).
# Status audit 2026-08-17 (independently counter-checked): Conjecture 20 is
# OPEN. New in Jul 2026: for iid Gaussian A in R^{(2m-1)xm}, (1/m) log
# omega(A) -> -log 4 in probability (Shmalo, arXiv:2607.06249), so the
# conjectured exponential decay holds for Gaussian matrices and any universal
# beta must be >= 1/4 - answering Open Problem 21 at exponential scale while
# leaving the worst-case-over-all-A conjecture untouched. Neighbor
# Conjecture 19 (complex injectivity at 4M-5): part (a) CLAIMED proven in a
# June-2026 AI-assisted note (arXiv:2606.17922), part (b) open - see
# calibration-phase-retrieval.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./balan_wang_stability.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set campaign.branch_step_budget "${OPENTORUS_BRANCH_STEPS:-40}"
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact singular values of all M-row submatrices (numpy / sympy for rational
# instances), optimization over frames (scipy), high precision (mpmath).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy mpmath
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/1308.4718
opentorus paper fetch https://arxiv.org/abs/2607.06249
opentorus paper fetch https://arxiv.org/abs/2603.29571

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Balan–Wang stability conjecture for phase retrieval at N = 2M−1

**Primary target (general).** For $A \in \mathbb{R}^{N \times M}$ define
$$\omega(A) = \min_{S \subseteq [N]:\ \operatorname{rank}(A_{S^c}) < M} \sigma_M(A_S),$$
the smallest $M$-th singular value of a row subset whose complement fails to span. The
complement property ($\omega(A) > 0$) is equivalent to injectivity of $x \bmod \pm 1
\mapsto |Ax|$, and Balan–Wang show the stability (Lipschitz) constants of phase
retrieval are governed by $1/\omega(A)$. **Conjecture (Balan–Wang; Randomstrasse101
Conjecture 20).** There exist universal constants $C > 0$ and $0 < \beta < 1$ such that
for every $M > 1$ and every $A \in \mathbb{R}^{(2M-1) \times M}$ in which any $M$ rows span
$\mathbb{R}^M$ (full spark — the minimal injective size),
$$\omega(A) \le C \max_{k \in [N]} \lVert A_k \rVert\, \beta^M ,$$
i.e. stability at the minimal number of measurements degrades exponentially in the
dimension, for every frame.

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**
(listed unchanged in the March 2026 archive,
[arXiv:2603.29571](https://arxiv.org/abs/2603.29571)). Background: real injectivity needs
$N \ge 2M-1$ and generic $2M-1$ suffice (Bandeira–Cahill–Mixon–Nelson, ACHA 2014, via
the complement property); Balan–Wang ([arXiv:1308.4718](https://arxiv.org/abs/1308.4718))
tie stability to $\omega$ and pose the conjecture. New and decisive for the *Gaussian*
case (Open Problem 21 of the post): Shmalo
([arXiv:2607.06249](https://arxiv.org/abs/2607.06249), Jul 2026) proves for iid
Gaussian $A \in \mathbb{R}^{(2m-1)\times m}$ that $\frac1m \log \omega(A) \to -\log 4$ in
probability, i.e. $\omega = 4^{-m + o_P(m)}$; with $R_m$ the max row norm,
$\mathbb P\{\omega(A) \le R_m b^m\} \to 1$ for every $b > 1/4$ (Gaussian frames obey the
conjectured form) and $\mathbb P\{\omega(A) \le C R_m b^m\} \to 0$ for every $b < 1/4$ and every
$C$ — so the conjecture FAILS whp on Gaussian frames for any $\beta < 1/4$, hence **any
universal $\beta$ must be $\ge 1/4$**; the general (all-$A$) statement is untouched (more
generally $N/m \to \gamma$: rate $-\log(\gamma^\gamma/(\gamma-1)^{\gamma-1})$ per real
dimension; the complex statement there concerns the square-submatrix quantity, not a complex
phase-retrieval $\omega$; the lower estimate extends to bounded-density ensembles). Neighbor: the complex injectivity conjecture at
$N = 4M-5$ (Conjecture 19) — part (a) "$p_M < 1$ for all $M$" is CLAIMED in a June-2026
4-page note (arXiv:2606.17922, "AI generated, human verified", unrefereed — it exhibits a
nonempty open set of non-injective $A$ for every $M \ge 2$), part (b) $\lim p_M = 0$ open;
"4M−4 necessary" is FALSE (Vinzant 2015: 11 injective vectors in $\mathbb{C}^4$; Huang
arXiv:2607.27719, Jul 2026 preprint: 10 never suffice) while "generic 4M−4 sufficient" is a
theorem (Conca–Edidin–Hering–Vinzant 2015).

**Known partial results (classified, with sources).**
- Complement property ⇔ injectivity; stability via $1/\omega$ (KNOWN_RESULTs;
  arXiv:1308.4718).
- Gaussian $\omega = 4^{-m+o(m)}$, hence $\beta \ge 1/4$ is forced by the $b < 1/4$ direction
  (KNOWN_RESULT from the parsed 2026 preprint — label the preprint status; not a proof of
  the conjecture).
- Under full spark the minimizing $S$ has $|S| = M$, so $\omega(A) = \min_{|S|=M}
  \sigma_M(A_S)$ (elementary; state and use it).
- Conjecture 19 layers: theorem (generic $4M-4$), false ("necessary"), claimed (part a),
  open (part b) — a neighbor, recorded with its labels.

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/omega.py — (a) exact $\omega(A)$ for full-spark $A \in
   \mathbb{R}^{(2M-1)\times M}$ by enumerating all $\binom{2M-1}{M}$ row subsets and their
   $M$-th singular value (numpy; $\le 92{,}378$ subsets for $M \le 10$), normalized by
   $\max_k \lVert A_k\rVert$; (b) for rational $A$, an exact certificate of a single
   $\sigma_M(A_S)$ (characteristic polynomial of $A_S^\top A_S$ in sympy, real-root
   isolation) so that reported values are certifiable; (c) generators: iid Gaussian,
   harmonic (DFT-real) frames, equiangular / Grassmannian frames, random unit-norm.
2. exp_new(title="Balan-Wang omega: Gaussian scaling and best-frame search",
   command="python scripts/omega.py", environment="python-sci",
   run_from="workspace") then exp_run — (i) Gaussian $A$, $M = 2..9$, hundreds of
   samples: median and spread of $\frac1M\log\omega$ vs $-\log 4 \approx -1.386$;
   (ii) maximize $\omega/\max\lVert A_k\rVert$ over $A$ (Nelder–Mead / basin hopping,
   many restarts) for $M = 2..7$ to estimate $b_M = \max_A \omega/\max\lVert A_k\rVert$
   and fit its decay base.
3. Submit exact facts via proof_submit (sympy backend): "for this rational $A$ (M=4),
   $\omega(A)/\max\lVert A_k\rVert = q$ exactly (all 35 subset values listed)". Only
   ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a family $A_M$ with $\omega(A_M)/\max\lVert A_k\rVert$
decaying slower than any $\beta^M$ (e.g. polynomially). A single frame never refutes;
the search for the best frame per $M$ (structured candidates first — harmonic and
equiangular frames — then optimization) yields the empirical $b_M$ sequence; if
$b_M^{1/M}$ shows no decay toward $< 1$, that is evidence against, and any explicit family
with a proof would refute. Every reported $\omega$ is exactly re-verified. A verified
counterexample claim must name the primary claim in depends_on.

**Proof track.** Reproduce the Gaussian $-\log 4$ law numerically as a calibration of the
tooling; test candidate lemmas ("$\omega$ is maximized by frames with equal row norms and
equiangular structure", "the minimizing $S$ can be taken to avoid any given row") against
the instance zoo; relate the extreme-singular-value machinery of the parsed 2026 paper to
what a worst-case bound would need; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact $\omega$ tables, Gaussian scaling
checks, best-frame optimization per $M$, structured-frame comparisons. Instances can
refute only via a proven family; they can never prove the universal statement.

**Claim policy.** Every conclusion is exactly one of: verified construction /
machine-checked theorem / exhaustive certified result / computational or numerical
evidence / conjecture / failed attempt. The campaign verdict is derived by
`opentorus problem verdict`; only GENERAL_CONJECTURE_PROVED or
GENERAL_CONJECTURE_REFUTED resolve the campaign.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Deterministic primary-claim designation ------------------------------
opentorus problem claim "${TARGET}" --type CONJECTURE \
  --statement "There exist universal constants C > 0 and 0 < beta < 1 such that for every M > 1 and every real (2M-1) x M matrix A in which any M rows span R^M, omega(A) <= C * max_k ||A_k|| * beta^M, where omega(A) is the minimum over row subsets S whose complement does not span of the M-th singular value of A_S."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 5)
# The campaign engine replaces the single prove session: a portfolio of branches
# (proof, counterexample, literature, formalization, ...) against the designated
# primary claim, scheduled and budgeted, pausable and resumable, replayable. The
# budget below bounds the run; every axis can be overridden from the environment.
# A finished campaign is orchestration state -- the mathematical status still comes
# from `opentorus problem verdict` (derived from accepted dossier artifacts only).
opentorus --verbose campaign start "${TARGET}" --mode prove-or-refute \
  --branches "${OPENTORUS_BRANCHES:-4}" \
  --max-steps "${OPENTORUS_MAX_STEPS:-200}" \
  --max-wall-seconds "${OPENTORUS_MAX_WALL_SECONDS:-0}"
CAMPAIGN="$(opentorus campaign list --problem "${TARGET}" --json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["campaign_id"])')"
opentorus campaign status "${CAMPAIGN}"
opentorus campaign tree "${CAMPAIGN}"
opentorus campaign verify "${CAMPAIGN}"   # replay the event log against the snapshot

# --- 8. Honest report, verdict, PDF ------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem verdict "${TARGET}"
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
