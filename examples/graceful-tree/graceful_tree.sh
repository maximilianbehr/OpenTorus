#!/usr/bin/env bash
# ============================================================================
# OpenTorus campaign example — The Graceful Tree Conjecture (Ringel–Kotzig)
# Built from examples/CAMPAIGN_TEMPLATE.md: general target, dated status audit,
# driver-designated primary claim, dual research process.
#
# Conjecture (1964). EVERY tree admits a graceful labeling: an injection
# f: V -> {0..|E|} such that the edge values |f(u)-f(v)| are exactly {1..|E|}.
# Status audit 2026-08-14: OPEN. Computer-verified for all trees on <= 35
# vertices; restricted classes proved (caterpillars, paths, olive trees,
# symmetric trees, some spiders); asymptotic relaxation proved ("almost all
# trees are almost graceful", arXiv:1608.01577). A 2007 claimed proof
# (arXiv:0709.2201) is not accepted by the community.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./graceful_tree.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus paper add https://arxiv.org/abs/1608.01577
opentorus paper add https://arxiv.org/abs/1003.3045
opentorus paper add https://arxiv.org/abs/1811.07614

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Graceful Tree Conjecture

**Primary target (general).** Every tree admits a graceful labeling: for every tree
$T = (V, E)$ there is an injection $f : V \to \{0, \dots, |E|\}$ whose induced edge values
$|f(u) - f(v)|$ are exactly $\{1, \dots, |E|\}$.

**Status audit (2026-08-14).** Fresh web check at creation: OPEN. Computer-verified for
all trees on $\le 35$ vertices ([arXiv:1003.3045](https://arxiv.org/abs/1003.3045)).
"Almost all trees are almost graceful" is proved
([arXiv:1608.01577](https://arxiv.org/abs/1608.01577)). A 2007 preprint claiming a complete
proof (arXiv:0709.2201) is **not accepted**; classify it as an unaccepted claim, never as
settling the conjecture.

**Known partial results (classified, with sources).**
- Graceful: paths, caterpillars, stars, olive trees, symmetric trees, spiders with
  restricted leg structure — record each as a KNOWN_RESULT with its source.
- Exhaustive verification for $|V| \le 35$ — computational, exact, scoped.
- Almost-graceful for almost all trees (arXiv:1608.01577) — an asymptotic relaxation,
  not the conjecture.

**START HERE — first tool actions of the proof phase, BEFORE any proof_write.**
1. write_file scripts/graceful_check.py: given a tree (edge list), decide gracefulness —
   exhaustive with complement symmetry breaking for small trees, z3 encoding for larger
   ones; print a labeling or UNSAT.
2. exp_new(title="graceful check all trees n<=10",
   command="python scripts/graceful_check.py --all-trees 10", environment="python-sci",
   run_from="workspace"), then exp_run.
3. Any UNSAT for a concrete tree: submit the encoding via proof_submit(backend="smt") —
   a machine-checked non-gracefulness certificate (below 36 vertices, expect none).
4. Only after EXP-0001 exists, write the status sketch (proof_write). A sketch without a
   single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a single tree with NO graceful labeling.
Per tree this is a finite CSP: encode labelings as SAT/SMT (z3) or exhaustive search with
symmetry breaking (complement symmetry f -> |E|-f). Generators: exhaustive trees at small
n (verified region reproduces), then structured families conjectured hard (high-degree
spiders, lobsters). An UNSAT result for one tree IS a machine-checkable non-gracefulness
certificate — submit via proof_submit(backend="smt") and record the claim with depends_on
on the primary claim. (Audit note: below 36 vertices everything is graceful, so any real
candidate is large — treat search as lemma-mining, not likely refutation.)

**Proof track.** Reproduce caterpillar/olive constructions as exact algorithms (sympy
checks per instance via proof_submit); mine labeling invariants from exhaustive small-n
data; candidate lemmas (e.g. edge-degree/decomposition arguments) tested against generated
trees before any proof_write uses them; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Per-tree gracefulness checks (both tracks),
class-construction verifiers, small-n exhaustive sweeps. No instance result resolves the
conjecture; the campaign verdict is derived by `opentorus problem verdict`.

**Claim policy.** Every conclusion is exactly one of: verified construction /
machine-checked theorem / exhaustive certified result / computational or numerical
evidence / conjecture / failed attempt.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 5b. Primary claim (driver-designated, deterministic) ---------------------
opentorus problem claim "${TARGET}" --type CONJECTURE \
  --statement "Every tree admits a graceful labeling (Ringel-Kotzig, 1964)."
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
