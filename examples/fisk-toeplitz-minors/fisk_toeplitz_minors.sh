#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Fisk's 3x3 Toeplitz-minor conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Theory and applications of total positivity"
#         (eds. P. K. Vishwakarma, P. N. Choudhury; AIM workshop July 2023), Problem
#         1.6 [P. Braenden]; http://aimpl.org/totalpos/1/ - identical to
#         Conjecture 3.2 [Fisk] on the 2011 AIM list "Stability,
#         hyperbolicity, and zero localization of functions",
#         http://aimpl.org/hyperbolicpoly/3/ (http only). Original: S. Fisk,
#         "Questions about determinants and polynomials", arXiv:0808.1850.
# Status audit 2026-08-17 (independently counter-checked): OPEN for 3x3 (and
# every m >= 3). Braenden proved the 2x2 case (Crelle 2011, arXiv:0909.1927);
# Yoshida (arXiv:1005.4218) proved the transform of (1+x)^n is real-rooted
# for every m and refuted the ADJACENT Fisk question a_k^2 - a_{k-r}a_{k+r}
# at r = 6. Creation-time computation: ~1350 random real-rooted polynomials
# of degree 4-12 (and 4x4/5x5/6x6 transforms), no failure; a symbolic
# discriminant argument proves the 3x3 case for degree <= 4.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./fisk_toeplitz_minors.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set model.timeout_seconds 2400
opentorus config set tools.verifiers.smt "${OPENTORUS_SMT:-false}"   # z3 on PATH: set OPENTORUS_SMT=true to let the formalizer use it
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted
opentorus config set campaign.branch_step_budget "${OPENTORUS_BRANCH_STEPS:-40}"
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact rational coefficient arithmetic and Sturm sequences (sympy), high
# precision root finding (mpmath), optimization searches (scipy).
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
opentorus paper fetch https://arxiv.org/abs/0808.1850
opentorus paper fetch https://arxiv.org/abs/0909.1927
opentorus paper fetch https://arxiv.org/abs/1005.4218

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Fisk's 3×3 Toeplitz-minor conjecture

**Primary target (general).** For every real-rooted polynomial
$p(z) = \sum_{k=0}^d a_k z^k$ with all $a_k > 0$ (set $a_j = 0$ outside $0..d$), the
polynomial
$$T_3[p](z) = \sum_{k \ge 0} \det\begin{pmatrix} a_k & a_{k-1} & a_{k-2} \\ a_{k+1} & a_k & a_{k-1} \\ a_{k+2} & a_{k+1} & a_k \end{pmatrix} z^k$$
is also real-rooted (and, in the 2011 phrasing, lies in the Laguerre–Pólya class
$\mathcal{L}\text{-}\mathcal{P}^+$; the coefficients are automatically positive). More
generally the $m \times m$ analogue $T_m[p]$ for every $m$. (Fisk 2008, Question 3; AIM
totalpos Problem 1.6 = hyperbolicpoly Conjecture 3.2. Useful reformulation: if
$p = \prod_i (1 + x_i z)$ then the $k$-th coefficient of $T_m[p]$ is the rectangular
Schur polynomial $s_{(m^k)}(x_1, \dots, x_d)$ by Jacobi–Trudi.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**
for $3 \times 3$ and every $m \ge 3$. Brändén proved the $2 \times 2$ case
([arXiv:0909.1927](https://arxiv.org/abs/0909.1927), Crelle 658 (2011); the conjecture
there is credited to Fisk and to McNamara–Sagan/Stanley) via a Pólya–Schur-type
characterization of the operators involved. Yoshida
([arXiv:1005.4218](https://arxiv.org/abs/1005.4218), CVEE 2013) proved $T_m[(1+x)^n]$ is
real-rooted for every $m$ and $n$ (Stanley's product formula for Toeplitz minors of
binomials + Malo–Schur–Szegő) and $T_m[e^x] \in \mathcal{L}\text{-}\mathcal{P}^+$; the same
paper settles the *adjacent* Fisk question ($a_k^2 - a_{k-r}a_{k+r}$ real-rooted) for
$r = 4$ but **refutes it for $r = 6$** (via the transcendental $S_6[e^x] \notin
\mathcal{L}\text{-}\mathcal{P}^+$, transferred through Brändén's characterization — no explicit
polynomial counterexample is written down; $r = 5$ and $r \ge 7$ remain open) — so "all of
Fisk's questions are true" is false, and the $3 \times 3$ question is genuinely uncertain.
The 2011 AIM page states the hypothesis for $p \in \mathcal{L}\text{-}\mathcal{P}^+$ (entire
functions with nonnegative coefficients), the 2023 page for polynomials; the July 2023
workshop report (aimath.org/pastworkshops/totalposrep.pdf) lists the approaches its working
group tried — Schur-sum generalization of Brändén's proof, skew-Schur functions, planar
networks, interlacing induction, Desnanot–Jacobi, a $q$-analogue of Yoshida's binomial
case — a ready-made program for the proof track. No proof, refutation, or claim was
found for $m \ge 3$. Creation-time computation (recompute, do not cite): $T_3$ on ~1350
random real-rooted polynomials of degree 4–12 (positive roots drawn uniform / lognormal /
clustered / geometric across $10^{\pm4}$ scales), ~400 checked by exact Sturm sequences —
no failure; likewise $T_4$ (1080), $T_5$ (720), $T_6$ (450); hill-climbing to minimize the smallest
relative root gap of $T_3[p]$ (gap divided by the larger root) never got below $\approx 0.4$
and converges to near-equal roots, i.e. the proven binomial case (the exact number depends
on the gap metric — define yours); symbolically, for degrees $2, 3, 4$ the discriminant
of $T_3[p]$ is a polynomial in the roots with all positive coefficients, which PROVES the
$3\times3$ case for degree $\le 4$ — a small verified partial theorem to reproduce.

**Known partial results (classified, with sources).**
- $m = 2$ (Brändén; KNOWN_RESULT).
- $p = (1+x)^n$ for all $m$; $e^x$ (Yoshida; KNOWN_RESULT).
- Degree $\le 4$ for $m = 3$ (creation-time discriminant argument — reproduce and
  certify via proof_submit before treating as a KNOWN_RESULT of this workspace).
- The $r = 6$ refutation of the adjacent question (KNOWN_RESULT; a neighbor showing that
  Fisk-type questions can fail).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/fisk_transform.py — (a) exact $T_m[p]$ for a polynomial with
   rational coefficients (sympy Rationals; zero-padding handled), (b) real-rootedness
   test by exact Sturm sequence (sympy count_roots) plus a fast mpmath pre-screen,
   (c) generators of real-rooted positive polynomials from random negative roots
   (several scale distributions), (d) a discriminant routine: for symbolic roots
   $x_1..x_d$, the discriminant of $T_3[p]$ as a polynomial in the $x_i$ (feasible for
   $d \le 4$).
2. exp_new(title="Fisk 3x3: random real-rooted search + small-degree discriminants",
   command="python scripts/fisk_transform.py", environment="python-sci",
   run_from="workspace") then exp_run — record: number of polynomials tested per
   degree and per $m$, minimum relative root gap of $T_3[p]$ found, and the sign
   pattern of the discriminant coefficients for $d = 2, 3, 4$.
3. Submit exact facts via proof_submit (sympy backend): "for $d = 3$, the discriminant of
   $T_3[\prod (1 + x_i z)]$ in $x_1, x_2, x_3$ has all positive coefficients, hence
   $T_3[p]$ is real-rooted for every real-rooted cubic with positive coefficients"; single
   instances "$T_3[p]$ for this rational $p$ has exactly $\deg$ real roots (Sturm)". Only
   ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: one real-rooted $p$ with positive coefficients such that
$T_3[p]$ has a non-real root — a rational root vector whose exact Sturm count is below the
degree, an exact certificate. Search: degrees 5–14, roots at wildly different scales,
clustered roots plus outliers, roots on geometric progressions, and optimization of the
minimal root gap / of the discriminant sign of $T_3[p]$ over root vectors (the $r = 6$
failure of the adjacent question suggests where irregular coefficient patterns bite).
Every candidate exactly re-verified; a verified counterexample claim must name the
primary claim in depends_on.

**Proof track.** Reproduce Brändén's $2\times2$ argument on the parsed paper and identify
why it does not lift (the $3\times3$ transform is cubic in the coefficients); reproduce
Yoshida's binomial case; extend the discriminant certificate to $d = 5$ if feasible
(size explodes — record where); test candidate lemmas (interlacing of $T_3[p]$ with
$T_2[p]$? total positivity of the minor matrix, Fisk's Question 4) on the zoo; every
unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Random and adversarial searches with exact
Sturm certificates, small-degree discriminant proofs, structured families. Instances can
refute (one exact certificate suffices); they can never prove the all-degree statement.

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
  --statement "For every real-rooted polynomial sum a_k z^k with all coefficients a_k > 0, the polynomial whose k-th coefficient is the 3x3 Toeplitz minor det[[a_k,a_{k-1},a_{k-2}],[a_{k+1},a_k,a_{k-1}],[a_{k+2},a_{k+1},a_k]] is also real-rooted."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 3)
# The campaign engine replaces the single prove session: a portfolio of branches
# (proof, counterexample, literature, formalization, ...) against the designated
# primary claim, scheduled and budgeted, pausable and resumable, replayable. The
# budget below bounds the run; every axis can be overridden from the environment.
# A finished campaign is orchestration state -- the mathematical status still comes
# from `opentorus problem verdict` (derived from accepted dossier artifacts only).
# Stress/coverage runs may adjust the workspace (budgets, profiles, backends) before the start.
[ -n "${OPENTORUS_PRESTART_HOOK:-}" ] && source "$OPENTORUS_PRESTART_HOOK"
opentorus --verbose campaign start "${TARGET}" --mode "${OPENTORUS_MODE:-prove-or-refute}" \
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
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem verdict "${TARGET}"
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
