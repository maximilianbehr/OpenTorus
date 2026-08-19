#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Lonely Runner conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-14, amended 2026-08-15 after peer cross-check: OPEN in
# general; computational landslide in low dimensions: settled for up to 13
# runners (k <= 12), the cases 8..13 all 2025-2026 computer-assisted preprints
# (Rosenfeld 8 runners arXiv:2509.14111; 9-and-10 arXiv:2511.22427; 9 also
# independently arXiv:2512.01912; 11-13 arXiv:2604.23906). 7 runners:
# Barajas-Serra 2008, arXiv:0710.4495. The general statement is open.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./lonely_runner.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact rational loneliness computation per speed set (three-distance /
# periodicity), covering-style searches, z3 for bounded refutation encodings.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy z3-solver
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/0710.4495
opentorus paper fetch https://arxiv.org/abs/2509.14111
opentorus paper fetch https://arxiv.org/abs/2511.22427
opentorus paper fetch https://arxiv.org/abs/2512.01912
opentorus paper fetch https://arxiv.org/abs/2604.23906

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Lonely Runner conjecture

**Primary target (general).** For every integer $k \ge 1$ and all distinct nonzero
integer speeds $v_1, \dots, v_k$, there exists a real time $t$ such that
$\lVert t\,v_i \rVert \ge \frac{1}{k+1}$ for every $i$, where $\lVert x\rVert$ denotes
the distance from $x$ to the nearest integer. (Equivalently: among $k+1$ runners on a
unit circle with pairwise distinct constant speeds, each runner is at some time at
circular distance $\ge \frac{1}{k+1}$ from all others.)

**Status audit (2026-08-14; amended 2026-08-15 after an independent cross-check).**
Fresh web check: **open in general**, with a recent computational landslide in low
dimensions. Settled for up to **13 runners** ($k \le 12$); the cases of 8 through 13
runners are all 2025–2026 computer-assisted preprints: Rosenfeld introduced a new
computational framework and settled 8 runners
([arXiv:2509.14111](https://arxiv.org/abs/2509.14111)); a sieve strengthening settled
9 and 10 ([arXiv:2511.22427](https://arxiv.org/abs/2511.22427)), with 9 also settled
independently and concurrently ([arXiv:2512.01912](https://arxiv.org/abs/2512.01912));
11–13 followed (Sungkawichai–Trakulthongchai,
[arXiv:2604.23906](https://arxiv.org/abs/2604.23906)). 7 runners was Barajas–Serra 2008
([arXiv:0710.4495](https://arxiv.org/abs/0710.4495)). Mixed-threshold
variants are active ([arXiv:2605.27941](https://arxiv.org/abs/2605.27941)). The general
statement — every $k$ — remains open.

**Known partial results (classified, with sources).**
- True for $\le 13$ runners ($k \le 12$); 8–13 all recent (2025/26) computer-assisted
  preprints — sources above (KNOWN_RESULTs; the 8/9/10/13-runner papers double as a
  reusable METHOD for the instance program). 7 runners: Barajas–Serra 2008.
- Tight instances: speeds $\{1,\dots,k\}$ achieve exactly $1/(k+1)$ — the bound cannot
  be improved (classical; classify with the parsed source).
- Reductions: it suffices to check finitely many speed sets per $k$ (bounded-speed
  reductions in the parsed literature; record the concrete bound from the papers, not
  from memory).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/loneliness.py — exact maximal loneliness
   $\sup_t \min_i \lVert t v_i\rVert$ of a GIVEN speed set by rational breakpoint
   enumeration (the function is piecewise linear; breakpoints are rationals with
   denominators dividing the $v_i$ — use sympy Rationals, no floats).
2. exp_new(title="Exact loneliness: tight family and perturbations",
   command="python scripts/loneliness.py", environment="python-sci",
   run_from="workspace") then exp_run — record exact values for the tight family
   $\{1..k\}$, $k = 3..8$, and at least 20 perturbed speed sets.
3. Convert each exact single-set result into a certificate and submit it via
   proof_submit (sympy backend): "speed set S has maximal loneliness exactly q,
   and q >= 1/(k+1)". Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a $k$ and distinct nonzero integer
speeds $v_1..v_k$ whose maximal loneliness $\sup_t \min_i \lVert t v_i\rVert$ is
$< 1/(k+1)$. For a FIXED speed set this quantity is exactly computable (the function is
piecewise linear with rational breakpoints — three-distance structure), so any candidate
is a finite certificate: exact rational maximization via sympy, certified via
proof_submit. Generators: near-tight perturbations of $\{1..k\}$, lacunary and
divisibility-structured sets, z3 bounded searches for $k \ge 13$ (below the proven
range nothing can exist). A verified counterexample claim must name the primary claim in
depends_on.

**Proof track.** Reproduce the Rosenfeld-style reduction pipeline on the smallest open
$k$ (as parsed from the papers): bounded-speed reduction, covering/sieve elimination of
speed-set classes, exact certification of the surviving finite checks via proof_submit
(sympy/interval — each eliminated class is a finite statement). Mine invariants from the
exact loneliness landscape (which structures approach $1/(k+1)$); candidate lemmas
tested against generated speed sets; every unresolved inference an explicit [GAP-n].

**Instance program (tools, not targets).** Exact loneliness computation for structured
families ($\{1..k\}$ variants, geometric/lacunary sets), landscape statistics near the
tight bound, and reproduction of one eliminated class from the 8-runner proof as a
certified finite check. Instances can refute for their $k$; only the all-$k$ statement
resolves the campaign.

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
  --statement "For every integer k >= 1 and all distinct nonzero integer speeds v_1..v_k, there exists a real time t such that the distance from t*v_i to the nearest integer is at least 1/(k+1) for every i."
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
