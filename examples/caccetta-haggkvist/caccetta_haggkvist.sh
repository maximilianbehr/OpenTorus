#!/usr/bin/env bash
# ============================================================================
# OpenTorus campaign example — The Caccetta–Häggkvist Conjecture
# Built from examples/CAMPAIGN_TEMPLATE.md.
#
# Conjecture (1978). EVERY digraph on n vertices with minimum out-degree at
# least n/k contains a directed cycle of length at most k. Status audit
# 2026-08-14: widely OPEN — even the k=3 (triangle) case is open; proved for
# digraphs with small independence number (arXiv:1908.02902); best triangle-
# case bounds are Shearer-type (out-degree ~0.3465 n forces a triangle);
# rainbow/Aharoni strengthenings are an active line (arXiv:1804.01317).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./caccetta_haggkvist.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set agent.prove_require_instance_work true  # campaign gate: force the instance-program attempt
if command -v z3 >/dev/null 2>&1; then
  opentorus config set tools.verifiers.smt true
fi

# --- 3. Numerical experiment environment ------------------------------------
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy networkx z3-solver
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids) -----------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/1908.02902
opentorus paper fetch https://arxiv.org/abs/1610.05292
opentorus paper fetch https://arxiv.org/abs/1804.01317

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Caccetta–Häggkvist Conjecture

**Primary target (general).** For every $k \ge 2$ and every digraph $D$ on $n$ vertices:
if every vertex has out-degree at least $n/k$, then $D$ contains a directed cycle of
length at most $k$.

**Status audit (2026-08-14).** Fresh web check at creation: widely OPEN — even the
$k = 3$ case (out-degree $\ge n/3$ forces a directed triangle) is open. Proved for
digraphs with independence number at most $(k+1)/2$
([arXiv:1908.02902](https://arxiv.org/abs/1908.02902)). Triangle case: Shearer-type
bounds show out-degree $\approx 0.3465\,n$ suffices (target: $n/3 \approx 0.3333\,n$).
Survey of the problem landscape: [arXiv:1610.05292](https://arxiv.org/abs/1610.05292);
rainbow/Aharoni strengthenings: [arXiv:1804.01317](https://arxiv.org/abs/1804.01317).

**Known partial results (classified, with sources).**
- Small independence number: conjecture holds (arXiv:1908.02902) — THEOREM with source.
- Triangle case constants: $0.3465n$ (Shearer-type) — THEOREM with source; the gap
  $[0.3333, 0.3465]$ is the open frontier.
- Known extremal candidates: iterated blow-ups of short cycles meet the bound with
  equality — reproduce as constructions, they show tightness, not truth.

**START HERE — first tool actions of the proof phase, BEFORE any proof_write.**
1. write_file scripts/ch_check.py: for given (n, k), decide with z3 whether some digraph
   on n vertices with min out-degree >= ceil(n/k) has directed girth > k (adjacency
   booleans; out-degree cardinality constraints; girth exclusion clauses); print
   SAT/UNSAT and any model.
2. exp_new(title="CH instance check n=9 k=3", command="python scripts/ch_check.py --n 9 --k 3",
   environment="python-sci", run_from="workspace"), then exp_run. Repeat for the largest
   (n, k) that stays under the timeout.
3. Every UNSAT instance: submit the encoding via proof_submit(backend="smt") — that makes
   it an exhaustive certified result for that (n, k).
4. Only after EXP-0001 exists, write the status sketch (proof_write). A sketch without a
   single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a digraph with min out-degree
$\ge n/k$ and directed girth $> k$. For fixed small $(n, k)$ this is a finite object:
SAT/SMT encoding (adjacency variables; out-degree cardinality constraints; girth
exclusion clauses) — z3-checkable, with symmetry breaking documented and
satisfiability-preservation argued per constraint. UNSAT for a given $(n,k)$ is an
exhaustive certified result FOR THAT $(n,k)$ (submit via proof_submit(backend="smt"));
SAT would give a candidate to verify independently and record with depends_on on the
primary claim. Honest note: decades of search found nothing; expect obstruction data,
not a refutation.

**Proof track.** Reproduce the Shearer-type computation on generated digraphs; test the
independence-number argument's boundary cases; mine degree/girth invariants from
exhaustive small-$(n,k)$ data; candidate lemmas checked against generated digraphs before
any proof_write uses them; finite checks via proof_submit; explicit [GAP-n] everywhere else.

**Instance program (tools, not targets).** Exhaustive/SAT sweeps over small $(n, k)$,
blow-up construction checks, bound reproductions. No instance resolves the conjecture;
the campaign verdict is derived by `opentorus problem verdict`.

**Claim policy.** Every conclusion is exactly one of: verified construction /
machine-checked theorem / exhaustive certified result / computational or numerical
evidence / conjecture / failed attempt.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 5b. Primary claim (driver-designated, deterministic) ---------------------
opentorus problem claim "${TARGET}" --type CONJECTURE \
  --statement "For every k >= 2, every digraph on n vertices with minimum out-degree at least n/k contains a directed cycle of length at most k (Caccetta-Haggkvist, 1978)."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 6. Dual-track campaign run ----------------------------------------------
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

# --- 7. Honest report + verdict + PDF ----------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem verdict "${TARGET}"
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
