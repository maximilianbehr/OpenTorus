#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Bukh's nonlinear Roth pattern x, y, y+P(x)-P(y)
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "High-dimensional phenomena in discrete analysis"
#         (ed. J. Lim; AIM workshop May 13-17, 2024, org. Conlon, Peluse,
#         Zhao), Problem 2.1 [Boris Bukh]; http://aimpl.org/highdimdiscrete/2/
#         (http only).
# Status audit 2026-08-17 (independently counter-checked): OPEN. Nothing is
# known beyond the linear case P(x) = 2x (Roth's theorem in F_p). The pattern
# is NOT a Peluse-type polynomial progression: the third term's shift
# P(x)-P(y) depends on the base point, the pattern is not translation-
# invariant, and none of the Bourgain-Chang / Peluse / Dong-Li-Sawin bounds
# apply to it. Exact maximum pattern-free sets for all primes p <= 59
# (P = x^2 and x^3) were computed at creation, twice, independently.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./bukh_nonlinear_roth.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact maximum pattern-free sets in F_p via SAT with cardinality constraints
# (python-sat / CaDiCaL), brute force for tiny p, sympy for exact algebra.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# All four are RELATED polynomial-progression results (x, x+y, x+y^2 and
# x, x+P1(y), x+P2(y)); none of them treats Bukh's pattern.
opentorus paper add https://arxiv.org/abs/1707.05977
opentorus paper add https://arxiv.org/abs/1709.00080
opentorus paper add https://arxiv.org/abs/1608.05448
opentorus paper add https://arxiv.org/abs/1909.00309

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Bukh's nonlinear Roth pattern $x,\ y,\ y + P(x) - P(y)$

**Primary target (general).** For every polynomial $P \in \mathbb{Z}[x]$ of degree at
least $2$ there is a constant $p_0(P)$ such that for every prime $p \ge p_0$ and every
set $A \subseteq \mathbb{F}_p$ with $|A| > p^{0.99}$, there exist distinct $x, y \in A$
with $y + P(x) - P(y) \in A$. (AIM highdimdiscrete Problem 2.1 [B. Bukh], verbatim: "Let
$P$ be any (non-linear) polynomial, $A \subset \mathbb{F}_p$ with $|A| > p^{0.99}$. Does
there always exist distinct $x, y$ such that $x, y, y + P(x) - P(y) \in A$? When
$P(x) = 2x$, this recovers Roth's Theorem on 3-APs." The page does not spell out
"$p$ large" or "$P \in \mathbb{Z}[x]$"; the reading above is the natural one — for
$P \in \mathbb{F}_p[x]$ of degree $\ge p$ the polynomial *function* can be linear, e.g.
$x^p = x$, and $x^3 = x$ on $\mathbb{F}_3$ — and must be stated as an interpretation.
Only $x \ne y$ is required; the third element may coincide with $x$ or $y$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
No paper, preprint, or claim addresses the pattern $x, y, y + P(x) - P(y)$ for any
nonlinear $P$; the only known case is the linear one ($P(x) = 2x$: Roth in
$\mathbb{F}_p$). Elementary observations (creation-time, unpublished): with $x = y + h$
the third term is $y + P(y+h) - P(y)$, so the "common difference" depends on the base
point $y$ — the pattern is **not translation-invariant** and is **not** a Peluse-type
polynomial progression $x, x + P_1(y), x + P_2(y)$; equivalently it is $a,\ b,\ Q(a) + P(b)$
with $Q = \mathrm{id} - P$. If $P(x) = P(y)$ for some $x \ne y$ (e.g. $P$ even, $y = -x$)
the pattern is present trivially, so for $P = x^2$ every pattern-free set has size
$\le (p+1)/2$; the interval $[a, 2a]$ with $a \approx \sqrt{p/2}$ is pattern-free for
$P = x^2$ (about $0.71\sqrt p$ elements, checked for $p$ up to $40009$). Related but
*not* special cases: Bourgain–Chang ([arXiv:1608.05448](https://arxiv.org/abs/1608.05448);
$x, x+y, x+y^2$ at density $\gg p^{-1/15}$, the exponent as quoted by Peluse), Peluse
([arXiv:1707.05977](https://arxiv.org/abs/1707.05977); $x, x+P_1(y), x+P_2(y)$ for
linearly independent $P_i$ with zero constant term, $\gg p^{-1/24}$), Dong–Li–Sawin
([arXiv:1709.00080](https://arxiv.org/abs/1709.00080); $\gg p^{-1/12}$, count
$\gtrsim \delta^3 p^2$), Peluse ([arXiv:1909.00309](https://arxiv.org/abs/1909.00309);
integers, distinct degrees, degree lowering), Kuca (arXiv:2304.10793, multidimensional),
Hong–Lim (arXiv:2401.01137, rational functions), Peluse–Prendiville–Shao
(arXiv:2407.08338), Altman–Sawhney (arXiv:2506.13010, transference). Do **not** cite their
density bounds for Bukh's pattern. Creation-time computation, run twice independently
(exact SAT with cardinality bisection, brute-force cross-checked for $p \le 19$):
maximum pattern-free $|A|$ for $P = x^2$ at $p = 3, 5, 7, 11, 13, 17, 19, 23, 29, 31,
37, 41, 43, 47, 53, 59$ is $2, 2, 2, 4, 4, 4, 5, 6, 7, 7, 8, 8, 9, 9, 10, 11$; for
$P = x^3$: $1, 2, 2, 4, 4, 5, 5, 6, 7, 7, 8, 9, 8, 10, 10, 11$ (the $p = 3$ value is
degenerate: $x^3 = x$ there). Growth $\approx p^{0.6}$–$p^{0.65}$ in this range; at
$p = 59$ the maximum is $11$ against $p^{0.99} = 56.6$ — the threshold $0.99$ is nowhere
near tight at small $p$ and is meant as "any power saving".

**Known partial results (classified, with sources).**
- Linear case = Roth in $\mathbb{F}_p$ (KNOWN_RESULT; classical, cite Peluse's
  introduction).
- Related polynomial-progression theorems (KNOWN_RESULTs; parsed sources) — related
  only.
- Trivial bounds and small-$p$ exact values (creation-time computation — recompute here,
  do not cite).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/bukh.py — (a) for a prime $p$ and $P$, the forbidden structure:
   pairs $\{x, y\}$ with $P(x) = P(y)$ or $P(x) - x = P(y) - y$ (third element coincides
   with $y$ resp. $x$) and triples $\{x, y, y + P(x) - P(y)\}$ otherwise; (b) an exact
   maximum pattern-free set via SAT with a cardinality constraint and bisection
   (python-sat, CaDiCaL), brute force for $p \le 19$ as a cross-check; (c) an $O(p^2)$
   checker for an explicit set.
2. exp_new(title="Bukh pattern: exact maximum pattern-free sets, P=x^2, p <= 59",
   command="python scripts/bukh.py --poly x2 --max-p 59", environment="python-sci",
   run_from="workspace") then exp_run — reproduce the table above, extend to $p \le 101$
   as budget allows, repeat for $P = x^3$, $x^2 + x$, $x^4$; fit the growth exponent.
3. Submit exact facts via proof_submit (sympy backend): "for $P = x^2$ and $p = 59$ the
   set $A = \{\dots\}$ of size $11$ is pattern-free" (explicit set + $O(p^2)$ check);
   "for $P = x^2$ every pattern-free set has size $\le (p+1)/2$" (the pairing argument).
   Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: one nonlinear $P$ and an infinite family of primes $p$
with pattern-free sets of size $> p^{0.99}$ — a construction, not a finite object; a
finite computation can only suggest one. Territory: polynomials whose difference
structure is degenerate (e.g. $P(x) = x^2$ restricted to a multiplicative subgroup,
$P$ with $P(x) - x$ constant on a large set — impossible for $\deg \ge 2$ over
$\mathbb{F}_p$, $p$ large, but check for small $p$), sets $A$ that are unions of
intervals or of cosets of multiplicative subgroups; watch the growth exponent as $p$
grows. A verified counterexample claim must name the primary claim in depends_on.

**Proof track.** The Fourier-analytic Roth argument fails because the pattern is not
translation-invariant; the higher-order/degree-lowering methods of Peluse are built for
progressions with a common base point. Formulate the counting operator
$\Lambda(f) = \mathbb{E}_{x,y} f(x) f(y) f(y + P(x) - P(y))$, test it on the small-$p$
data, and try to control it via the two-variable polynomial $F(x,y) = y + P(x) - P(y)$
(a Weil-type bound on the number of solutions when $A$ is a "random" set;
an averaging over $y$ that reduces to a Peluse-type pattern for fixed $y$ — record
exactly where the reduction fails). Every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact maxima for $p \le 100$ and several
$P$, growth-exponent fits, structure of extremal sets. Instances can neither prove nor
refute the all-$p$ statement; a construction beating $p^{0.99}$ for all large $p$
would.

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
  --statement "For every polynomial P with integer coefficients of degree at least 2 there is a constant p_0 such that for every prime p >= p_0 and every set A of residues modulo p with |A| > p^{0.99}, there exist distinct x, y in A with y + P(x) - P(y) in A."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 4)
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
