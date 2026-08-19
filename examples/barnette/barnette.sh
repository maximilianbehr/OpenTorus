#!/usr/bin/env bash
# ============================================================================
# OpenTorus campaign example — Barnette's Conjecture
# Built from examples/CAMPAIGN_TEMPLATE.md.
#
# Conjecture (Barnette 1969). EVERY 3-connected cubic planar bipartite graph is
# Hamiltonian. Status audit 2026-08-14: OPEN. Verified for n <= 90 vertices;
# Goodey's six-edge-face case proved; the related Barnette-Goodey conjecture
# (cubic planar, faces <= 6) was proved by Kardos (2020); best structural
# partial solutions via facial 2-factors (Bagheri et al. 2021) and matching
# theory (arXiv:2202.11641); Georges-Kelmans minimality for the non-bipartite
# relative (arXiv:2101.00943).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./barnette.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus paper fetch https://arxiv.org/abs/2101.00943
opentorus paper fetch https://arxiv.org/abs/2202.11641
opentorus paper fetch https://arxiv.org/abs/2309.09578

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Barnette's Conjecture

**Primary target (general).** Every 3-connected cubic planar bipartite graph is
Hamiltonian.

**Status audit (2026-08-14).** Fresh web check at creation: OPEN. Exhaustively verified
for all such graphs on $n \le 90$ vertices (and edge-through-cycle variants for
$n \le 78$ / $n \le 66$). Goodey: true when all big faces have six edges. The *related*
Barnette–Goodey conjecture (cubic planar, all faces $\le 6$, no bipartiteness) was
**proved by Kardoš (2020)** — record it as a settled neighbor, never conflate it with the
target. Best structural partials: facial 2-factors (Bagheri et al., JGT 2021), matching
theory ([arXiv:2202.11641](https://arxiv.org/abs/2202.11641)), sufficient conditions
([arXiv:2309.09578](https://arxiv.org/abs/2309.09578)).

**Known partial results (classified, with sources).**
- $n \le 90$ exhaustive verification — computational, exact, scoped.
- Goodey's six-edge-face theorem; Kardoš 2020 (neighboring conjecture, settled).
- Reductions: it suffices to prove Hamiltonicity through any two chosen edges of a face
  (folklore reductions — cite from parsed papers only).

**START HERE — first tool actions of the proof phase, BEFORE any proof_write.**
1. write_file scripts/barnette_check.py: given a cubic planar bipartite graph (edge list),
   decide Hamiltonicity (exact DP or z3 encoding); include a generator for small instances
   of the class (prism-like and face-merge constructions).
2. exp_new(title="Barnette Hamiltonicity sweep small n",
   command="python scripts/barnette_check.py --sweep 20", environment="python-sci",
   run_from="workspace"), then exp_run.
3. Certify one representative instance's Hamiltonian cycle exactly via
   proof_submit(backend="sympy") (cycle as witness, checked against the edge list).
4. Only after EXP-0001 exists, write the status sketch (proof_write). A sketch without a
   single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is one 3-connected cubic planar bipartite
non-Hamiltonian graph — necessarily $n > 90$ per the audit. Generators: bipartite planar
cubic expansions of known non-Hamiltonian *non-bipartite* relatives (Georges–Kelmans
family, arXiv:2101.00943) and face-merge constructions. Per candidate, Hamiltonicity is a
finite check: SAT/SMT encoding (z3) or exact DP; a certified NO instance would be the
counterexample — verify independently (two encodings), record with depends_on on the
primary claim. Honest expectation: the verified region makes discovery unlikely; treat
the search as obstruction-mining.

**Proof track.** Reproduce Goodey-type conditions on generated families; test the
matching-theory and facial-2-factor lemmas against exhaustive small-n data; explore
whether known reductions compose; every unresolved inference is an explicit [GAP-n],
and finite lemma checks go through proof_submit, not exp_run.

**Instance program (tools, not targets).** Exhaustive Hamiltonicity sweeps for small n
(reproducing the verified region on generated samples), per-candidate certified checks,
lemma validation runs. No instance resolves the conjecture; the campaign verdict is
derived by `opentorus problem verdict`.

**Claim policy.** Every conclusion is exactly one of: verified construction /
machine-checked theorem / exhaustive certified result / computational or numerical
evidence / conjecture / failed attempt.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 5b. Primary claim (driver-designated, deterministic) ---------------------
opentorus problem claim "${TARGET}" --type CONJECTURE \
  --statement "Every 3-connected cubic planar bipartite graph is Hamiltonian (Barnette, 1969)."
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
