#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Constant-degree sum-of-squares refutation of
#                              k-colorability below the Kesten–Stigum bound
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Connecting communities via the block model"
#         (ed. A. Wein; AIM workshop May 22-26, 2017), Section 3 "Hardness
#         at the KS threshold", Problem 3.2 [Cris Moore];
#         http://aimpl.org/blockmodel/3/ (http only).
# Status audit 2026-08-17 (independently counter-checked): OPEN as posed for
# constant SoS degree > 2 at constant average degree d. Degree 2 (Lovasz
# theta) is settled: it fails far above KS - theta refutes k-colorability of
# random d-regular graphs only once d >~ 4(k-1)^2 (Banks-Kleinberg-Moore,
# arXiv:1705.01194; Banks-Trevisan arXiv:1907.02539 for G(n,d/n)); BKM
# conjecture that no constant-degree SoS refutation exists below KS, and quiet
# spectral planting (arXiv:2008.12237) gives low-degree evidence that
# certification is hard all the way to ~4(k-1)^2. Dense/large-d SoS lower
# bounds exist (Kothari-Manohar; Potechin-Xu STOC 2025 for log n <= d << sqrt n,
# no arXiv), nothing at constant d. Note the KS bound for planted k-coloring
# is (k-1)^2 in G(n,d/n) ((k-1)^2+1 regular); the page's k^2 is the large-k
# approximation.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./sos_coloring_ks.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Random regular / ER graphs (networkx), spectra (numpy/scipy), SDP for theta
# and small degree-4 SoS relaxations (cvxpy + Clarabel), exact rational
# pseudo-moment certificates (sympy).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy networkx cvxpy clarabel
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/1705.01194
opentorus paper fetch https://arxiv.org/abs/1907.02539
opentorus paper fetch https://arxiv.org/abs/2008.12237
opentorus paper fetch https://arxiv.org/abs/2406.18429

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Constant-degree SoS refutation of k-colorability below the Kesten–Stigum bound

**Primary target (general).** For every $k \ge 3$ and every constant SoS degree $D$: for
random graphs of constant average degree $d$ below the Kesten–Stigum bound of the planted
$k$-coloring model — $d < (k-1)^2$ for $G(n, d/n)$, $d < (k-1)^2 + 1$ for random
$d$-regular graphs (the AIM page's "$k^2$" is the large-$k$ approximation) — the
degree-$D$ sum-of-squares relaxation does NOT refute $k$-colorability with high
probability, i.e. a degree-$D$ pseudo-expectation for the coloring constraints
($x_{v,c}^2 = x_{v,c}$, $\sum_c x_{v,c} = 1$, $x_{u,c}x_{v,c} = 0$ for $uv \in E$) exists.
(AIM blockmodel Problem 3.2, C. Moore, asks the question "can constant-degree SoS refute
$k$-colorability below KS?"; the conjectured answer — the campaign's primary claim — is
NO, as stated explicitly by Banks–Kleinberg–Moore. Below KS the graphs are already
non-$k$-colorable whp for $d \gtrsim 2k\ln k$; the question is about certification.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open as
posed** for constant $D > 2$ at constant $d$; settled for $D = 2$. Degree 2 = Lovász
$\vartheta$: on random $d$-regular graphs $\vartheta(G_{n,d}) = d/(2\sqrt{d-1}) + \Theta(1)$
(Banks–Kleinberg–Moore, [arXiv:1705.01194](https://arxiv.org/abs/1705.01194)), so
$\vartheta$ fails to refute whenever $k > 2 + d/(2\sqrt{d-1})$ (roughly $d \lesssim 4(k-2)^2$)
and refutes only for $d \gtrsim 4(k-1)^2$ — far above KS; BKM explicitly conjecture that
SoS refutations of any constant degree do not exist below KS. For $G(n,d/n)$ the vector
chromatic number is $\tfrac12\sqrt d + o_d(1)$ (Banks–Trevisan,
[arXiv:1907.02539](https://arxiv.org/abs/1907.02539)), same picture. Quiet spectral
planting (Bandeira–Banks–Kunisky–Moore–Wein,
[arXiv:2008.12237](https://arxiv.org/abs/2008.12237)) gives BP / local-statistics /
low-degree evidence that no poly-time algorithm certifies $\chi(G_{n,d})$ beyond the
Hoffman bound $1 + d/(2\sqrt{d-1})$ — i.e. hardness conjecturally extends to
$\approx 4(k-1)^2$, not just KS; the local-statistics SDP hierarchy fails below KS in the
degree-regular block model (Banks–Mohanty–Raghavendra, arXiv:1911.01960). Rigorous SoS
lower bounds exist only in denser regimes: dense $G(n,1/2)$ (Kothari–Manohar,
arXiv:2105.07517) and, per its published abstract, $\log n \le d \ll \sqrt n$
(Potechin–Xu, STOC 2025, DOI 10.1145/3717823.3718151 — no arXiv; the full text is
paywalled, so its exact sparse hypothesis is unconfirmed here) — with polylog losses,
nothing at constant $d$. The closest technology at constant $d$: SoS lower bounds for
independent set in ultra-sparse $G(n,d/n)$ (Kothari–Potechin–Xu,
[arXiv:2406.18429](https://arxiv.org/abs/2406.18429)) and graph-matrix norm bounds on
random $d$-regular graphs (Xu, arXiv:2411.14314, CCC 2025) — coloring not done.
Creation-time computation (recompute, do not cite): on random $d$-regular graphs with
$n = 700$, the Hoffman certificate $1 + d/|\lambda_{\min}|$ refutes 3-colorability at
$d = 16$ but not $d = 12$; 4-col at $d = 36$ not $20$; 5-col at $d = 64$ not $30$ —
consistent with the $\approx 4(k-1)^2$ degree-2 threshold and far above KS ($5, 10, 17$).

**Known partial results (classified, with sources).**
- Degree-2 (theta / vector chromatic number) thresholds (KNOWN_RESULTs; parsed sources).
- Quiet-planting evidence, local-statistics SDP failure (KNOWN_RESULTs; evidence-grade
  by their own nature — say so).
- Dense/log-$n$ SoS lower bounds (KNOWN_RESULTs; Potechin–Xu journal-only, hypothesis
  unconfirmed — mark).
- BKM's explicit conjecture (the primary claim's provenance).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/sos_coloring.py — (a) random $d$-regular and $G(n,d/n)$ samplers;
   (b) the exact KS table $(k-1)^2$ / $(k-1)^2 + 1$ and the degree-2 thresholds
   $2 + d/(2\sqrt{d-1})$, $1 + d/(2\sqrt{d-1})$; (c) the Hoffman certificate and the
   $\vartheta$ SDP (cvxpy) on samples; (d) a degree-4 SoS relaxation of $k$-colorability
   for small $n$ ($\le 40$–$60$ vertices; moment matrix over degree-$\le 2$ monomials in
   the $x_{v,c}$, symmetry-reduced by color permutations) returning feasible/infeasible,
   and — for a feasible instance — an exact rational pseudo-moment matrix certificate
   (round, project onto the affine constraints, verify PSD by exact LDLᵀ).
2. exp_new(title="SoS coloring: degree-2 thresholds and degree-4 feasibility below KS",
   command="python scripts/sos_coloring.py", environment="python-sci",
   run_from="workspace") then exp_run — reproduce the Hoffman/theta table; then for
   $k = 3, 4$ and $d$ just below KS, solve degree-4 SoS on samples with $n$ as large as
   the solver allows and record feasibility rates vs $d$ and $n$.
3. Submit exact facts via proof_submit (sympy backend): "this explicit rational degree-4
   pseudo-moment matrix is PSD and satisfies all coloring constraints for this graph"
   (a per-instance certificate that degree-4 SoS does NOT refute this graph). Only
   ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track (of the primary claim = a positive answer to Moore's question).**
Negate: an explicit constant-degree SoS refutation family below KS. Search: does
degree-4 SoS refute $k$-colorability on samples at some $d < (k-1)^2$ where theta does not?
(A refutation on a fixed graph is a certificate; a *family* with proof would refute the
claim.) Track the empirical degree-4 threshold vs $d$; compare with the Hoffman bound.

**Proof track (pseudo-expectation constructions).** Reproduce the pseudo-calibration
template from the parsed KPX paper at small size; test whether the planted-coloring
pseudo-distribution's degree-4 moment matrix is PSD on samples below KS (exact
certificates where feasible); relate to the graph-matrix norm bounds needed at constant
$d$; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Degree-2 threshold tables, degree-4
feasibility rates on small samples, exact pseudo-moment certificates. Instances certify
single graphs; the asymptotic "no pseudo-expectation" / "pseudo-expectation exists whp"
statements need proofs (a positive answer needs an explicit refutation family; a negative
answer needs a pseudo-calibration + norm-bound argument).

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
  --statement "For every k >= 3 and every constant D, for random graphs of constant average degree d below the Kesten-Stigum bound (d < (k-1)^2 for G(n,d/n)), the degree-D sum-of-squares relaxation does not refute k-colorability with high probability as n tends to infinity."
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
