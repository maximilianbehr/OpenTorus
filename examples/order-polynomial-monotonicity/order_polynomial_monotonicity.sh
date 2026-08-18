#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Kahn–Saks order-polynomial monotonicity
#                              conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Ehrhart polynomials: inequalities and extremal
#         constructions" (ed. D. Hanely; AIM workshop May 9-13, 2022),
#         Problem 2.12; http://aimpl.org/ehrhartineq/2/ (http only).
#         Origin: Stanley, EC1, Exercise 3.163(b) [5] - a question raised by
#         J. Kahn and M. Saks (unpublished; NOT their 1984 balancing paper).
# Status audit 2026-08-17 (independently counter-checked): OPEN. Named the
# "Kahn-Saks monotonicity conjecture" by Chan-Pak-Panova (SIAM JDM 2023,
# arXiv:2205.02798) who prove monotonicity along t, 2t, 4t, ... and give
# stronger implying conjectures; trivial when Omega has nonnegative
# coefficients (skew-shape cell posets, fence and circular fence posets -
# Ferroni-Morales-Panova arXiv:2503.16403); Omega can have negative
# coefficients from n = 5 on. Verified at creation for every poset with
# n <= 9 (t <= 12) and with a complete all-t certificate for n <= 8.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./order_polynomial_monotonicity.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# nauty genposetg (Debian package; nauty-prefixed binaries symlinked) to
# stream posets up to isomorphism; exact order polynomials by counting
# multichains of order ideals (sympy rationals).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nauty \
 && rm -rf /var/lib/apt/lists/* \
 && for f in /usr/bin/nauty-*; do ln -sf "$f" "/usr/bin/${f#/usr/bin/nauty-}"; done
RUN pip install --no-cache-dir numpy sympy networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2205.02798
opentorus paper add https://arxiv.org/abs/2311.02743
opentorus paper add https://arxiv.org/abs/2503.16403
opentorus paper add https://arxiv.org/abs/1806.08403

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Kahn–Saks order-polynomial monotonicity conjecture

**Primary target (general).** For every finite poset $P$ with $n$ elements, let
$\Omega(P,t)$ be its order polynomial (the number of order-preserving maps $P \to [t]$;
$\Omega(P, t+1)$ is the Ehrhart polynomial of the order polytope $\mathcal O(P)$). Then
$$\frac{\Omega(P,t)}{t^n} \text{ is nonincreasing in } t \in \mathbb{Z}_{>0}.$$
(Kahn–Saks, as recorded in Stanley, *Enumerative Combinatorics I*, Exercise 3.163(b);
AIM ehrhartineq Problem 2.12. Equivalently: $\Omega(P,t)(t+1)^n \ge \Omega(P,t+1)t^n$
for every $t \ge 1$ — the probability that a uniformly random map $P \to [t]$ is
order-preserving does not increase with $t$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
Origin: an unpublished question of Kahn and Saks recorded by Stanley (EC1, Ex. 3.163: part
(a) shows $\Omega(P,t)/t^n$ is eventually decreasing, strictly unless $P$ is an antichain,
since the coefficient of $t^{n-1}$ is positive; part (b), rated [5], asks whether it is
decreasing for all $t$) — it is NOT the Kahn–Saks 1984 balancing conjecture, and the
2025 "Kahn–Saks conjecture" papers by Aires–Kahn concern balancing, not this. Named the
"Kahn–Saks monotonicity conjecture" by Chan–Pak–Panova
([arXiv:2205.02798](https://arxiv.org/abs/2205.02798), SIAM J. Discrete Math. 2023,
Conj. 4.12), who prove $\Omega(P,t)/t^n \ge \Omega(P,kt)/(kt)^n$ for all integers
$k, t \ge 1$ (monotone along $t, 2t, 4t, \dots$; an injection with defect in #P), show
$\Omega(P,t)/t^w$ is weakly *increasing* for the width $w$, give stronger conjectures
implying it (their Conj. 4.17; also Conj. 4.12 of the Chan–Pak survey), and note the
geometric analogue $\mathrm{Ehr}(Q,t-1)/t^d$
fails for Reeve tetrahedra. Trivial when $\Omega$ has nonnegative coefficients — cell
posets of skew shapes, all fence/zig-zag and circular fence posets
(Ferroni–Morales–Panova, [arXiv:2503.16403](https://arxiv.org/abs/2503.16403), v3 Jul
2026, §8.5 lists the conjecture open); but $\Omega$ has negative coefficients already for
four 5-element posets (Stanley 3.164), e.g. $C_1 \oplus A_{n-1}$ with
$\Omega = \sum_{k \le t} k^{n-1}$ (mind the Ehrhart shift $\Omega(P,t) = i(\mathcal O(P), t-1)$:
order polytopes themselves are Ehrhart-positive up to dimension 13 and non-positive
examples exist in every dimension $\ge 14$ — Liu–Tsuchiya,
[arXiv:1806.08403](https://arxiv.org/abs/1806.08403); Liu–Xin–Zhang, arXiv:2412.07164). Survey: Chan–Pak ([arXiv:2311.02743](https://arxiv.org/abs/2311.02743),
§4.3). No proof, refutation, or claim found 2023–2026. Creation-time computation (exact
rationals over isomorphism classes, counts 1, 2, 5, 16, 63, 318, 2045, 16999, 183231 =
OEIS A000112): no violation for any poset with $n \le 9$ and $t \le 12$; a complete
all-$t$ certificate for every poset with $n \le 8$; and a stronger empirical pattern:
$D(t) := \Omega(t)(t+1)^n - \Omega(t+1)t^n$ has all nonnegative coefficients in $t+1$
for every non-antichain poset with $n \le 8$.

**Known partial results (classified, with sources).**
- Eventually decreasing; nonneg-coefficient case; the $t \to kt$ monotonicity; width
  version increasing (KNOWN_RESULTs; parsed sources).
- Nonneg-coefficient classes (skew shapes, fences) (KNOWN_RESULT; FMP preprint — label).
- Small-$n$ verification (creation-time computation — recompute here, do not cite).
- CPP's stronger conjectures (CONJECTURE layer).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/order_poly.py — (a) exact $\Omega(P,t)$ for a poset given as a
   digraph6 Hasse diagram (genposetg -o) via multichains of order ideals — $\Omega(P,t)$
   is the $(\emptyset, P)$ entry of $Z^t$ for the zeta matrix $Z$ of the lattice $J(P)$
   of order ideals — or by direct DP; interpolate the polynomial exactly (sympy
   Rationals); (b) $D(t) = \Omega(t)(t+1)^n - \Omega(t+1)t^n$ and a complete per-poset
   certificate: $D(t) \ge 0$ for $t = 1..T$ plus a root bound (Cauchy/Newton) for $t > T$;
   (c) the coefficient sign pattern of $\Omega$ and of $D(t+1)$.
2. exp_new(title="Kahn-Saks monotonicity: exhaustive posets n <= 7",
   command="genposetg -o 7 -q | python scripts/order_poly.py", environment="python-sci",
   run_from="workspace") then exp_run — complete certificates for all posets on
   $\le 7$ elements (2045 classes; push to 8 = 16999 as budget allows), record how many
   have negative $\Omega$-coefficients and still satisfy the conjecture, and test the
   "$D(t+1)$ has nonnegative coefficients" pattern.
3. Submit exact facts via proof_submit (sympy backend): "for the poset $C_1 \oplus A_4$,
   $\Omega(t) = \sum_{k \le t} k^4$ and $D(t) \ge 0$ for all $t \ge 1$" (exact algebra);
   "all 2045 posets on 7 elements satisfy the conjecture for all $t$" (per-poset
   certificates). Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: one poset $P$ and one integer $t$ with $D(t) < 0$ — a
finite, exactly certifiable object. Territory: $n \ge 10$; posets with many negative
$\Omega$-coefficients (ordinal sums $C_1 \oplus A_{n-1}$-like, "wide-then-thin" shapes),
small $t$ (the eventual decrease is a theorem, so violations can only be at small $t$
relative to $n$); random posets on 10–14 elements; targeted families from Liu–Tsuchiya's
negative-Ehrhart constructions. A verified counterexample claim must name the primary
claim in depends_on.

**Proof track.** Reproduce CPP's $t \to kt$ injection on instances; test the
$D(t+1)$-nonnegativity pattern (a strengthening that, if true, implies the conjecture) and
CPP's Conj. 4.17 on the zoo; identify which structural feature of $P$ correlates with the
minimum of $D(t)$ over $t$; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Complete per-poset certificates for small
$n$, coefficient-sign statistics, targeted searches at $n = 10..14$, tests of the
strengthenings. Instances can refute (one certified pair suffices); they can never prove
the all-$P$ statement.

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
  --statement "For every finite poset P with n elements and every positive integer t, Omega(P,t)/t^n >= Omega(P,t+1)/(t+1)^n, where Omega(P,t) is the number of order-preserving maps from P to [t]."
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
