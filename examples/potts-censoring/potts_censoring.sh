#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Censoring inequality for the ferromagnetic
#                              Potts model from a constant start
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Markov chain mixing times" (eds. A. Ben-Hamou,
#         R. Gheissari; AIM workshop June 6-10, 2016), Section 1 "Spin
#         systems", Problem 1.5 [Yuval Peres]; http://aimpl.org/markovmixing/1/
#         (http only).
# Status audit 2026-08-17 (independently counter-checked): OPEN. The
# Peres-Winkler censoring inequality (arXiv:1112.0603, CMP 2013) covers
# MONOTONE spin systems from the top configuration; ferromagnetic Potts with
# q >= 3 is not monotone. Holroyd (arXiv:1101.4690, JSP 2011) refuted the
# analogue for proper colourings, lazy transpositions and ANTIferromagnetic
# 4-state Potts (for large enough coupling) and states the ferromagnetic
# constant-start case is open; Gheissari-Lubetzky use censoring only on the
# monotone FK dynamics. Creation-time exhaustive computation on tiny graphs
# (independently re-run): zero violations, while the controls (antiferro,
# non-constant starts) reproduce known violations.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./potts_censoring.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted
opentorus config set campaign.branch_step_budget "${OPENTORUS_BRANCH_STEPS:-40}"
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact distributions on q^n states as tensors (numpy), exact rational
# arithmetic for certificates (sympy Rationals with exp(beta) symbolic or
# rational weights), graph handling (networkx).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/1112.0603
opentorus paper fetch https://arxiv.org/abs/1101.4690
opentorus paper fetch https://arxiv.org/abs/1109.6075
opentorus paper fetch https://arxiv.org/abs/1607.02182

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The censoring inequality for the ferromagnetic Potts model from a constant start

**Primary target (general).** For every finite graph $G = (V,E)$, every $q \ge 3$, every
inverse temperature $\beta > 0$ (ferromagnetic $q$-state Potts measure
$\pi(\sigma) \propto \exp(\beta\sum_{ij \in E}\mathbf 1\{\sigma_i = \sigma_j\})$ on
$\{1..q\}^V$), every deterministic sequence of heat-bath single-site updates
$v_1, v_2, \dots, v_L$ (site $v_t$ resampled from $\pi(\cdot \mid \sigma_{V \setminus v_t})$)
started from a constant configuration (all sites in one color, "all green"), and every
subsequence obtained by deleting ("censoring") some of the updates:
$$\lVert \mu_{\text{censored}} - \pi\rVert_{TV} \;\ge\; \lVert \mu_{\text{full}} - \pi\rVert_{TV},$$
i.e. censoring updates can only increase the total-variation distance to stationarity.
(AIM markovmixing Problem 1.5, Y. Peres. Known for monotone systems from the top by
Peres–Winkler; the Potts model with $q \ge 3$ is not monotone.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
Peres–Winkler ([arXiv:1112.0603](https://arxiv.org/abs/1112.0603), CMP 323 (2013), Thm
1.1): for a monotone system started at the top (or any $\mu_0$ with $\mu_0/\pi$
increasing), deleting updates gives $\mu \preceq \nu$ and $\lVert\mu-\pi\rVert \le
\lVert\nu-\pi\rVert$, also for random schedules — and they note monotonicity cannot be
dropped, citing Holroyd. Holroyd ([arXiv:1101.4690](https://arxiv.org/abs/1101.4690), JSP
145 (2011)): extra updates CAN delay mixing for proper 4-colourings of a triangle, for
lazy transpositions, and for the ANTIferromagnetic 4-state Potts model on a triangle from
the all-1 start when the coupling is large enough; he states explicitly that the
ferromagnetic constant-start case is open. Fill–Kahn
([arXiv:1109.6075](https://arxiv.org/abs/1109.6075), AAP 2013, §8) recover and extend
censoring via comparison inequalities — but only for (partially) ordered spins with
positive correlations, so nothing for unordered Potts spins. Gheissari–Lubetzky
([arXiv:1607.02182](https://arxiv.org/abs/1607.02182)) write that "the monotonicity
requirement of the censoring prevents us from carrying this out in the setting of the
Potts Glauber dynamics" and use censoring only on the monotone FK/random-cluster dynamics.
No proof, refutation, or claim found 2016–2026 (Blanca–Rafid, arXiv:2607.09841, Jul 2026,
analyse systematic scan for mean-field Potts without any censoring tool). Structural
fact: a violation for a subsequence reduces, by a chain of single deletions, to a
violation for a single deleted update — so exhaustive search over schedules of length
$\le L$ with single deletions is complete for that $L$. Creation-time computation (exact
tensor arithmetic, heat-bath $\mathbb P(\sigma_v = s \mid \text{rest}) \propto
\exp(\beta\,\#\{u \sim v : \sigma_u = s\})$, start all-0; independently re-run):
$q = 3$ ferromagnetic on $K_3, P_3$ (all schedules $L \le 8$), $K_4, C_4, P_4$, star$_4$
($L \le 6$), $K_5, C_5, P_5$ ($L \le 6$), $C_6$ ($L \le 5$), $\beta \in \{0.3, \dots, 4\}$,
plus 30k random longer schedules — ZERO cases where deleting an update decreased the TV
distance; controls: Holroyd's antiferromagnetic $q = 4$ triangle violation reproduced
(e.g. $\beta = -2$: TV .0715 vs .0661), antiferro $q = 3$ on $K_3$ violates, and
ferromagnetic Potts / Ising from NON-constant starts violate (as expected).

**Known partial results (classified, with sources).**
- Peres–Winkler for monotone systems; Fill–Kahn generalization (KNOWN_RESULTs; neither
  covers Potts $q \ge 3$).
- Holroyd's counterexamples for colourings / transpositions / antiferro Potts
  (KNOWN_RESULTs; neighbors that show what the ferro constant start is protecting).
- FK-dynamics censoring (KNOWN_RESULT; a different chain).
- Exhaustive tiny-graph verification (creation-time computation — recompute here).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/potts_censoring.py — (a) exact distribution evolution: represent
   $\mu$ as a $q^{|V|}$ tensor, apply heat-bath updates at given sites exactly (numpy
   float64 first; sympy Rationals with $w = e^\beta$ kept symbolic or rational for
   certificates), compute $\pi$ and TV; (b) enumerate all schedules of length $\le L$
   and all single deletions; report $\max(\mathrm{TV}_{\text{full}} - \mathrm{TV}_{\text{censored}})$;
   (c) controls: antiferromagnetic $\beta < 0$, non-constant starts, Ising $q = 2$.
2. exp_new(title="Potts censoring: exhaustive tiny graphs + controls",
   command="python scripts/potts_censoring.py", environment="python-sci",
   run_from="workspace") then exp_run — reproduce the zero-violation table above and the
   controls; then extend: $q = 3, 4$ on $K_4, C_5, K_{2,3}$, the 2×3 grid, $\beta$ on a
   finer grid including large $\beta$ (near-frozen dynamics) and tiny $\beta$; random
   schedules of length 10–20 with random deletions.
3. Submit exact facts via proof_submit (sympy backend): "for $q = 3$ ferromagnetic Potts
   on $K_3$ with $e^\beta = 2$, for every schedule of length $\le 6$ and every single
   deletion, $\mathrm{TV}_{\text{censored}} \ge \mathrm{TV}_{\text{full}}$ (exact rationals)".
   Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: one graph, $q$, $\beta$, schedule and one deleted update
with $\mathrm{TV}_{\text{censored}} < \mathrm{TV}_{\text{full}}$ — an exact rational certificate
(rational $e^\beta$). Where to look, guided by Holroyd's mechanism (a censored update
that would have "reset" a site into a configuration far from equilibrium): graphs with
frustration-like structure for ferro Potts (odd cycles, $K_{2,3}$), schedules that update
one site twice in a row vs once, moderate $\beta$ where the all-green start is far from
$\pi$ but not frozen; adaptive search maximizing $\mathrm{TV}_{\text{full}} - \mathrm{TV}_{\text{censored}}$
over $\beta$ and schedules. A verified counterexample claim must name the primary claim
in depends_on.

**Proof track.** Reproduce Peres–Winkler's stochastic-domination argument on the parsed
paper and identify the exact step that needs monotonicity; test whether the
random-cluster coupling transfers censoring from FK dynamics to Potts from a constant
start (the constant start is where the two are closest); test candidate lemmas ("from a
constant start, $\mu_t/\pi$ stays Schur-convex in the color counts") on the exact
instance zoo; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exhaustive schedule/deletion searches on tiny
graphs with exact certificates, controls that reproduce Holroyd's violations, adaptive
searches for the largest negative gap. Instances can refute (one certified violation
suffices); they can never prove the all-graphs statement.

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
  --statement "For every finite graph, every q >= 3, every beta > 0, every deterministic sequence of heat-bath single-site updates of the ferromagnetic q-state Potts model started from a constant configuration, and every subsequence obtained by deleting updates, the total variation distance to stationarity after the censored sequence is at least that after the full sequence."
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
