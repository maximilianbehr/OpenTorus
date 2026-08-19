#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Hadamard conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): the GENERAL
# conjecture (order 4k for every k) is OPEN. The finite frontier moved days
# before this audit: on 2026-08-12/13 an Anthropic team (Alpoge, Voinov,
# Reynolds-Haertle, and Claude) ANNOUNCED explicit Hadamard matrices for all
# twelve previously unknown orders < 2000 (668, 716, 892, 1132, 1244, 1388,
# 1436, 1676, 1772, 1916, 1948, 1964) via an X post; third-party integer
# replay confirms the matrices, but there is no arXiv paper and no peer
# review — the announcement stays "claimed, machine-checkable, unrefereed".
# Everything below 2000 before that: smallest unknown 668 (since the 2005
# publication of order 428, Kharaghani-Tayfeh-Rezaie).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./hadamard.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact integer arithmetic for H*H^T = nI checks (numpy int64 / sympy),
# Paley/Sylvester/Williamson constructions, SAT for small-order searches.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/2411.18897
opentorus paper fetch https://arxiv.org/abs/1003.4001
opentorus paper fetch https://arxiv.org/abs/2401.15381

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Hadamard conjecture

**Primary target (general).** For every positive integer $k$ there exists a Hadamard
matrix of order $4k$: an $n \times n$ matrix $H$ with entries $\pm 1$ and
$H H^{\mathsf T} = n I$, $n = 4k$. (Orders $1$ and $2$ aside, the order of a Hadamard
matrix is necessarily a multiple of $4$; the conjecture is the converse.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: the
general conjecture is **open** — no proof or refutation. The finite frontier moved
*days before this audit*: on 2026-08-12/13 a team at Anthropic (Alpöge, Voinov,
Reynolds-Haertle, and the model Claude) **announced** explicit Hadamard matrices for
all twelve previously unknown orders below 2000
($668, 716, 892, 1132, 1244, 1388, 1436, 1676, 1772, 1916, 1948, 1964$), published as
raw sign data in a social-media post; at audit time at least one third party had
re-verified the matrices by exact integer arithmetic, but there is **no arXiv paper and
no peer review** — record it as *claimed, machine-checkable, unrefereed*, and re-verify
locally before treating any order as settled. Before that announcement the smallest
unknown order was $668 = 4 \cdot 167$ (open since order 428 was settled —
Kharaghani–Tayfeh-Rezaie, JCD 13, published 2005). Construction landscape: Sylvester
($2^m$), Paley ($q+1$, $2(q+1)$ for prime powers $q$), Williamson-type (nonexistence of
Williamson matrices at $n = 35$: Đoković 1993; at $n = 47, 53, 59$:
Holzmann–Kharaghani–Tayfeh-Rezaie, DCC 2008); asymptotics: existence of orders
$k \cdot 2^t$ with $t$ logarithmic in $k$ (Craigen–Livinskyi line; recent explicit bound
Du–Jiang, [arXiv:2401.15381](https://arxiv.org/abs/2401.15381)) and positive density
(de Launey, [arXiv:1003.4001](https://arxiv.org/abs/1003.4001)); a curated construction
database covering all known orders (Cati–Pasechnik,
[arXiv:2411.18897](https://arxiv.org/abs/2411.18897)). The density of settled orders in
$4\mathbb{N}$ is still $0$.

**Known partial results (classified, with sources).**
- Sylvester and Paley constructions; Williamson/Goethals–Seidel arrays (KNOWN_RESULTs;
  cite the parsed database paper for the catalogue).
- Asymptotic existence: for every odd $k$, orders $k \cdot 2^t$ exist for $t$
  logarithmic in $k$ (KNOWN_RESULT; Du–Jiang arXiv:2401.15381 and references therein —
  record the concrete bound from the parsed paper, not from memory).
- Positive density of settled orders in a relaxed sense (de Launey arXiv:1003.4001).
- The twelve sub-2000 orders: CLAIMED (unrefereed 2026 announcement) — never
  KNOWN_RESULT unless re-verified locally, and even then the *matrices* are verified,
  not the announcement's provenance.
- Williamson nonexistence at 35 (Đoković 1993), 47/53/59 (HKT-R 2008) — the ansatz
  fails, not the conjecture (KNOWN_RESULTs).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/hadamard_tools.py — (a) exact verifier: for an integer matrix H,
   check entries in {+1, -1} and H*H^T == n*I (integer arithmetic only), (b) Sylvester
   doubling and the Paley I/II constructions (quadratic residues over GF(q)), (c) the
   Goethals-Seidel array assembling four circulants into a Hadamard matrix.
2. exp_new(title="Hadamard: constructions and exact verification",
   command="python scripts/hadamard_tools.py", environment="python-sci",
   run_from="workspace") then exp_run — construct and exactly verify orders 4..100
   covered by Sylvester/Paley (record which orders in that range need other methods:
   the classical gaps 92, 116, 156, ...), and verify one Goethals-Seidel instance.
3. Submit each verified order as a certificate via proof_submit (sympy backend):
   "the explicit matrix H_n satisfies H H^T = n I with entries +-1". Only ACCEPTED
   submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample would be an order $4k$ with NO Hadamard
matrix — a nonexistence statement over a search space of size $2^{n^2}$, far beyond any
exhaustive check for relevant $n$. Honest scope: nonexistence is provable only within a
restricted ansatz (e.g. "no Williamson matrices of order n", a finite SAT instance —
reproduce the known $n = 35$ result at small scale if feasible). No route to refuting
the full conjecture is known; record this as the structural asymmetry of the problem.

**Proof track.** Reproduce the classical constructions with exact verification; map
which residues/orders each method covers and certify the coverage statements for
concrete ranges via proof_submit; parse the asymptotic-existence arguments and identify
what a density-1 or all-$k$ statement would additionally need; every unresolved
inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact verification of constructed matrices,
coverage tables for Sylvester/Paley/Williamson over $4k \le 2000$, small-order SAT
searches within ansätze. Instances can settle single orders (constructively); they can
never prove the all-$k$ statement, and practical nonexistence proofs exist only inside
restricted ansätze.

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
  --statement "For every positive integer k there exists a Hadamard matrix of order 4k, i.e. a 4k x 4k matrix with entries +-1 whose rows are pairwise orthogonal."
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
