#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Smale's mean value conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): OPEN. No accepted
# proof of K = 1, nor of the sharp form K = (d-1)/d; the arXiv proof claims
# (Schmieder 2002; Wang 2017, withdrawn; Ma-Ma 2022) are all unaccepted.
# Best general bounds: K <= 4 (Smale 1981), 4^{(d-2)/(d-1)} (Beardon-Minda-Ng
# 2002), 4(d-1)/(d+1) (Conte-Fujikawa-Lakic 2007), K < 4 - 2.263/sqrt(d) for
# d >= 8 (Crane 2007). Sharp for d <= 4 (Tischler) and d = 5 (Crane, CMFT
# 2006, published computational proof); 6 <= d <= 10 numerically only
# (Marinov-Sendov 2007, not certified). Active frontier is the DUAL
# conjecture (proved d <= 7, arXiv:2303.17586; best universal dual bound
# 1/d^2, Dubinin). CAUTION: Sendov's conjecture (see calibration-sendov) is
# a different problem.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./smale_mean_value.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact root isolation and rational arithmetic (sympy), high-precision and
# interval evaluation (mpmath) for certified S(p) enclosures, optimization
# searches over critical-point parametrizations.
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
opentorus paper fetch https://arxiv.org/abs/2303.17586
opentorus paper fetch https://arxiv.org/abs/0906.4605
opentorus paper fetch https://arxiv.org/abs/1609.00170

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Smale's mean value conjecture

**Primary target (general).** For every complex polynomial $p$ of degree $d \ge 2$ and
every $z \in \mathbb{C}$ with $p'(z) \ne 0$, there is a critical point $\zeta$ of $p$
($p'(\zeta) = 0$) with
$$\left|\frac{p(z) - p(\zeta)}{z - \zeta}\right| \le K\,|p'(z)|, \qquad K = 1.$$
(Smale 1981. The sharp conjectured constant is $K = (d-1)/d$, attained by
$p(z) = z^d - dz$ at $z = 0$; proving ANY $K < 4$ uniformly in $d$ would already be a
breakthrough. Normalized form: WLOG $z = 0$, $p(0) = 0$, $p'(0) = 1$; then the claim is
$\min_\zeta |p(\zeta)/\zeta| \le K$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
No accepted proof of $K = 1$ or of the sharp form; the claimed proofs on arXiv are all
unaccepted (Schmieder math/0206174, never published; Wang 1703.06627, withdrawn by the
author; Ma–Ma 2211.02402, unpublished). No 2024–2026 proof claim. Best general bounds on
the optimal constant $K(d)$: $K \le 4$ (Smale 1981, via Koebe 1/4);
$K \le 4^{(d-2)/(d-1)}$ (Beardon–Minda–Ng, Math. Ann. 322 (2002));
$K \le 4\frac{d-1}{d+1}$ (Conte–Fujikawa–Lakic, Proc. AMS 135 (2007));
$K < 4 - \frac{2.263}{\sqrt d}$ for $d \ge 8$ (Crane, Bull. LMS 39 (2007) — best for
large $d$). Settled sharp cases: $d = 2, 3, 4$ (Tischler 1989 line) and $d = 5$
(Crane, Comput. Methods Funct. Theory 6 (2006), a published computational proof;
$M_5 = 4/5$); $6 \le d \le 10$ rests on numerical maximization only (Marinov–Sendov
2007, not a certified proof). Special classes: polynomials with real zeros / zeros of
equal modulus / conservative polynomials (Tischler); odd polynomials with nonzero linear
term ($K \le 2$, Ng 2003); real critical points ($2/3$, Hinkkanen–Kayumov 2010). The
active frontier is the DUAL mean value conjecture ($\max_\zeta |p(\zeta)/\zeta| \ge
\frac{1}{d}\,$; Dubinin–Sugawa, [arXiv:0906.4605](https://arxiv.org/abs/0906.4605)):
proved for $d \le 7$ (Hinkkanen–Kayumov–Khammatova,
[arXiv:2303.17586](https://arxiv.org/abs/2303.17586), Constr. Approx. 61 (2025)) and for
odd polynomials (Tang 2510.16875); general dual bounds $1/(d4^d)$, $1/4^d$ (Ng–Zhang,
[arXiv:1609.00170](https://arxiv.org/abs/1609.00170)), $\frac1d\tan(\pi/(4d))$ and later
$1/d^2$ (Dubinin — the best universal dual bound). CAUTION: Sendov's conjecture (a
different problem — see the calibration-sendov example) and the Smale conjecture on
$\mathrm{Diff}(S^3)$ must not have their status imported here.

**Known partial results (classified, with sources).**
- The $K(d)$ upper-bound ladder (KNOWN_RESULTs; journal-only entries marked as such,
  constants taken from parsed sources).
- Sharp $d \le 4$ (KNOWN_RESULT) and $d = 5$ (KNOWN_RESULT; Crane, CMFT 2006 —
  journal-only, metadata marked as such if not fetched); $6 \le d \le 10$:
  NUMERICAL_EVIDENCE, never KNOWN_RESULT.
- The dual conjecture results (KNOWN_RESULTs from the parsed papers) — neighbors that
  calibrate techniques, not the target.
- The unaccepted proof claims: CLAIMED layer, each with its arXiv fate (withdrawn /
  unpublished).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/smale_ratio.py — normalized setting p(0)=0, p'(0)=1: (a) for a
   polynomial given by rational coefficients, isolate ALL critical points with certified
   enclosures (sympy real/complex root isolation on p', or mpmath with rigorous error
   control), (b) compute a certified upper bound on S(p) = min over critical points of
   |p(zeta)/zeta|, and (c) exact evaluation for the extremal candidate p(z) = z^d - d z
   (S = (d-1)/d, exact by algebra).
2. exp_new(title="Smale ratio: extremal family and search",
   command="python scripts/smale_ratio.py", environment="python-sci",
   run_from="workspace") then exp_run — verify S(z^d - dz) = (d-1)/d exactly for
   d = 2..8; random rational polynomials d = 3..6 (a few hundred): certified S(p)
   values; a hill-climbing search over critical-point parametrizations maximizing S(p)
   for d = 4, 5 (does anything beat (d-1)/d - epsilon?).
3. Submit exact facts via proof_submit (sympy backend): "S(z^d - dz) = (d-1)/d for
   d = 5" (exact algebra); "for this rational p, S(p) <= q < 1" (certified enclosure
   stated with its error bound). Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample to $K = 1$ is a polynomial $p$
(normalized) with $\min_\zeta |p(\zeta)/\zeta| > 1$; against the sharp form, $> (d-1)/d$.
For a FIXED rational polynomial this is a finite, certifiable computation (isolate the
$d-1$ critical points, certify a LOWER bound on every $|p(\zeta)/\zeta|$). Search:
gradient/annealing over the critical-point parametrization (fix $\zeta_1 \dots \zeta_{d-1}$,
integrate to get $p$), which is where the known extremal structure lives; degrees
5–8. Candidates get exact rational completion and certification. A verified
counterexample claim must name the primary claim in depends_on. Note the asymmetry:
beating $(d-1)/d$ refutes the sharp form only; beating $1$ refutes Smale's conjecture.

**Proof track.** Reproduce the extremality data around $z^d - dz$ (is it a strict local
maximum of S in the parametrization? — numerically, then exactly where feasible); mine
the search landscape for structure (all critical values used? equal moduli?); test
candidate lemmas from the dual-conjecture technology against the instance zoo; every
unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Certified S(p) enclosures, the extremal
family exactly, landscape statistics for d = 4..8. Instances can refute (one certified
polynomial suffices); they can never prove the all-(d, p, z) statement — that needs a
rigorous global argument (e.g. certified branch-and-bound over a compact parameter
space, per fixed degree).

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
  --statement "For every complex polynomial p of degree d >= 2 and every z with p'(z) != 0, some critical point zeta of p satisfies |p(z) - p(zeta)| <= |z - zeta| * |p'(z)|."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 5)
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
