#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Lovász number of random circulant graphs
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: Randomstrasse101 open-problems blog (ETH Zurich), "The Lovasz
#         number for random graphs (problems 17 and 18)", D. Dmitriev,
#         2025-05-21; https://randomstrasse101.math.ethz.ch/posts/lovasz-circulant/
#         Archived as arXiv:2603.29571 (Open Problems of 2025).
# Status audit 2026-08-17 (independently counter-checked): Conjecture 18 -
# E theta(G) = (1+o(1)) sqrt(n) for a random dense circulant graph - is
# OPEN; rigorous sqrt(n) <= E theta <= C sqrt(n log log n)
# (Bandeira-Blasiok-Dmitriev-Faure-Kireeva-Kunisky, arXiv:2502.16227). Its
# sibling Conjecture 17 for G(n,1/2) is OPEN with the 40-year-old bounds
# sqrt(n) <= E theta <= 2 sqrt(n) (lower: Lovasz 1979 + symmetry; upper:
# Juhasz 1982) and a competing heuristic conjecture E theta < 1.55 sqrt(n)
# (Feige-Grinberg, arXiv:2506.02952). For circulant graphs theta is a linear
# program - exact rational certificates per instance, and n ~ 1e4-1e5 is
# routine, which is why the circulant conjecture is the primary target here.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./lovasz_theta_random.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# LP for circulant theta (scipy HiGHS), exact rational LP re-checks (sympy),
# SDP for general graphs (cvxpy + Clarabel), FFT (numpy).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy networkx cvxpy clarabel
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2502.16227
opentorus paper add https://arxiv.org/abs/2506.02952
opentorus paper add https://arxiv.org/abs/1907.05971

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Lovász number of random dense circulant graphs

**Primary target (general).** For a graph $G$ on $n$ vertices let
$\vartheta(G) = \max\{\sum_{i,j} X_{ij} : X \succeq 0,\ \mathrm{Tr}\,X = 1,\ X_{ij} = 0
\text{ for } ij \in E(G)\}$ be the Lovász theta function ($\alpha(G) \le \vartheta(G) \le
\chi(\overline G)$). A *random dense circulant graph* on $n$ vertices is the Cayley graph of
$\mathbb{Z}/n$ whose connection set contains each chord length $k \in \{1..\lfloor(n-1)/2\rfloor\}$
(together with $n-k$) independently with probability $1/2$ (the source paper takes $n$ odd).
**Conjecture 18 (Randomstrasse101):** for every such $n$, with $G$ random dense circulant,
$$\mathbb E\,\vartheta(G) = (1 + o(1))\sqrt n \quad (n \to \infty).$$
Since $\vartheta(G)\vartheta(\overline G) = n$ for vertex-transitive graphs (Lovász) and $G$,
$\overline G$ are equidistributed, this says $\vartheta(G)/\sqrt n \to 1$ in mean — the
theta function of a random circulant graph concentrates at the geometric mean of the
trivial bounds.

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**
(restated unchanged in the March 2026 archive, arXiv:2603.29571). Rigorous:
$\sqrt n \le \mathbb E\vartheta(G) \le C\sqrt{n\log\log n}$
(Bandeira–Błasiok–Dmitriev–Faure–Kireeva–Kunisky,
[arXiv:2502.16227](https://arxiv.org/abs/2502.16227), Thm 1) — the lower bound from
$\vartheta(G)\vartheta(\overline G) = n$ plus Jensen, the upper bound via the frequency-domain
linear program (circulant matrices are diagonalized by the DFT, so $\vartheta$ of a
circulant graph is an LP — Magsino–Mixon–Parshall,
[arXiv:1907.05971](https://arxiv.org/abs/1907.05971)) and RIP of subsampled DFT matrices;
the paper notes its RIP strategy cannot remove the $\log\log n$. Sibling **Conjecture 17**
for $G(n,1/2)$: $\mathbb E\vartheta = (1+o(1))\sqrt n$ — open, with the rigorous bounds
$\sqrt n \le \mathbb E\vartheta \le 2\sqrt n$ unchanged for 40+ years (lower: Lovász 1979 +
symmetry; upper: Juhász 1982, who gives $(1/2-o(1))\sqrt n \le \vartheta \le (2+o(1))\sqrt n$
whp), and a competing *heuristic* conjecture $\mathbb E\vartheta < 1.55\sqrt n$ from new
poly-time upper bounds (Feige–Grinberg,
[arXiv:2506.02952](https://arxiv.org/abs/2506.02952), explicitly not a proof). Paley graphs
are the deterministic circulant analogue (there $\vartheta(\overline{G_p}) = \sqrt p$
exactly; see the paley-clique example).

**Known partial results (classified, with sources).**
- $\sqrt n \le \mathbb E\vartheta \le C\sqrt{n\log\log n}$ (KNOWN_RESULT; arXiv:2502.16227).
- $\vartheta(G)\vartheta(\overline G) = n$ for vertex-transitive $G$ (KNOWN_RESULT; Lovász 1979).
- The LP formulation for circulant graphs (KNOWN_RESULT; arXiv:1907.05971).
- $G(n,1/2)$: $[\sqrt n, 2\sqrt n]$ rigorous; Feige–Grinberg $1.55$: CONJECTURE layer.

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/circulant_theta.py — (a) sample random dense circulant graphs;
   (b) $\vartheta$ via the frequency-domain LP (variables $y_0..y_{n-1}$ with
   $y_k = y_{n-k}$, $\lVert y\rVert_1 = 1$, $y \ge 0$, $\langle y, f_k\rangle = 0$ for chords
   $k$ in the connection set; maximize $n y_0$ — take the exact form from the parsed
   paper) with scipy HiGHS; (c) an exact rational re-check of a solved instance's optimal
   basis (sympy Fractions on the real cosine formulation) yielding a primal–dual
   certificate for that graph; (d) the SDP for general graphs (cvxpy) as a cross-check
   on small $n$.
2. exp_new(title="Random circulant theta: E theta / sqrt(n) curves",
   command="python scripts/circulant_theta.py", environment="python-sci",
   run_from="workspace") then exp_run — Monte Carlo $\mathbb E\vartheta/\sqrt n$ for
   $n$ odd on a geometric grid up to $10^4$ (or as far as budget allows), with confidence
   intervals; the joint distribution of $(\vartheta(G)/\sqrt n, \sqrt n/\vartheta(G))$;
   exhaustive over all $2^{(n-1)/2}$ circulants for $n \le 25$; for $G(n,1/2)$ the SDP for
   $n \le 200$ as a comparison table.
3. Submit exact facts via proof_submit (sympy backend): "for this circulant graph on
   $n = 101$ vertices with connection set $S$, $\vartheta(G) = q$ exactly (rational
   primal–dual certificate)". Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: $\limsup \mathbb E\vartheta/\sqrt n > 1$. Evidence only —
the curves' behaviour (does the ratio plateau above 1, does it drift like $\sqrt{\log\log n}$?);
mine the extremal circulants at each $n$ (which connection sets maximize $\vartheta$? do
arithmetic structures dominate?) for a candidate structured family with provably larger
$\vartheta$ — a family with a proof would refute; no table does. A verified counterexample
claim must name the primary claim in depends_on.

**Proof track.** Reproduce the LP + Jensen lower bound exactly on instances; test the
dual (frequency-domain) certificates the parsed paper builds and see where the RIP step
loses $\log\log n$; test candidate lemmas ("the optimal LP support concentrates on
$O(\sqrt n)$ frequencies") against the instance zoo; every unresolved inference is an
explicit [GAP-n].

**Instance program (tools, not targets).** LP-exact $\vartheta$ for random and exhaustive
small circulants, ratio curves, extremal-set mining, $G(n,1/2)$ SDP comparison. Instances
can never prove the asymptotic statement; only a family with a proof refutes.

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
  --statement "For every n, let G be a random dense circulant graph on n vertices (each chord length present independently with probability 1/2); then the expected Lovasz theta number satisfies E theta(G) = (1 + o(1)) sqrt(n) as n tends to infinity."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 3)
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
