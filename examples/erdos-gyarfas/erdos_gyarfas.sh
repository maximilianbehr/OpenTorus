#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Erdős–Gyárfás conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): OPEN. Settled
# classes: planar claw-free (Daniel-Shauger 2001), 3-connected cubic planar
# (Heckman-Krakovski 2013), K_{1,m}-free with min degree >= m+1 or max degree
# >= 2m-1 (Shauger 1998), P8-/P10-/P13-free (2022-2025), diameter-2 with min
# degree 3 (arXiv:2508.19302). Large AVERAGE degree forces a power-of-2 cycle
# (Liu-Montgomery, JAMS 2023, arXiv:2010.15802 — not the conjecture itself).
# Counterexample lower bounds: no cubic counterexample < 30 vertices
# (Markström 2004); cubic bipartite needs >= 60 (arXiv:2608.02675, Aug 2026).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./erdos_gyarfas.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# nauty (geng/genbg via Debian package; the binaries are nauty-prefixed, so
# symlink them) for exhaustive graph generation, networkx for cycle spectra,
# python-sat for "no power-of-2 cycle" encodings.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nauty \
 && rm -rf /var/lib/apt/lists/* \
 && for f in /usr/bin/nauty-*; do ln -sf "$f" "/usr/bin/${f#/usr/bin/nauty-}"; done
RUN pip install --no-cache-dir numpy sympy networkx python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/2010.15802
opentorus paper fetch https://arxiv.org/abs/2608.02675
opentorus paper fetch https://arxiv.org/abs/2410.22842

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Erdős–Gyárfás conjecture

**Primary target (general).** For every finite simple graph with minimum degree at least
3, there is a cycle in the graph whose length is a power of 2. (Erdős–Gyárfás, posed ~1994/95, published
1997. Not to be confused with the same authors' generalized-Ramsey function $f(n,p,q)$
or with monochromatic path/cycle partition problems.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**;
the August 2026 literature explicitly calls it unresolved. Settled classes: planar
claw-free graphs (Daniel–Shauger 2001); 3-connected cubic planar graphs
(Heckman–Krakovski 2013, computer-assisted discharging); $K_{1,m}$-free graphs with
minimum degree $\ge m+1$ *or* maximum degree $\ge 2m-1$ (Shauger 1998); $P_8$-free
(Gao–Shan 2022), $P_{10}$-free (Hu–Shen, Discrete Math. 347 (2024),
[arXiv:2308.05675](https://arxiv.org/abs/2308.05675)), $P_{13}$-free
(Hegde–Sandeep–Shashank, [arXiv:2410.22842](https://arxiv.org/abs/2410.22842),
computer-aided); diameter-2 graphs with min degree 3 contain a 4- or 8-cycle (Carr,
[arXiv:2508.19302](https://arxiv.org/abs/2508.19302)). Sufficiently large *average*
degree forces a power-of-2 cycle (Liu–Montgomery, JAMS 36 (2023),
[arXiv:2010.15802](https://arxiv.org/abs/2010.15802) — an absolute-constant
average-degree theorem; it does not decide minimum degree 3). Structure of a minimal
counterexample: predominantly cubic — a regular minimal counterexample is cubic, and
$\ge 4/7$ of its vertices have degree 3 (Carr,
[arXiv:2605.22844](https://arxiv.org/abs/2605.22844)). Counterexample lower bounds: no
counterexample below 17 vertices (Royle and Markström); no cubic counterexample below 30
vertices, and four 24-vertex cubic graphs whose only power-of-2 cycle length is 16 — the
tightest known instances (Markström 2004); every cubic bipartite graph on $\le 58$
vertices has a 4-, 8- or 16-cycle, so cubic bipartite counterexamples need $\ge 60$
vertices (Tranquilli, [arXiv:2608.02675](https://arxiv.org/abs/2608.02675), Aug 2026,
exhaustive search; cites an unrefereed 2026 GitHub computation excluding all
min-degree-3 graphs through order 31).

**Known partial results (classified, with sources).**
- The settled classes above (KNOWN_RESULTs; cite parsed sources; keep Shauger's two
  alternatives intact).
- Liu–Montgomery average-degree theorem (KNOWN_RESULT; the parsed paper states the
  precise form — record it from the paper, not from memory).
- Sudakov–Verstraëte: graphs with no power-of-2 cycle have average degree
  $e^{O(\log^* n)}$ (KNOWN_RESULT; arXiv:0707.2117 if parsed, else mark journal-only).
- Markström's 24-vertex extremal cubic graphs — the hardest known instances (a METHOD
  anchor for the instance program).
- The order-31 GitHub exclusion: CLAIMED (unrefereed) — separate from the refereed layer.

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/pow2_cycles.py — (a) an exact cycle-length-spectrum routine
   (which cycle lengths occur; DFS/bitset over induced paths, feasible to ~30 vertices
   for sparse graphs), (b) a check "has a cycle of length in {4, 8, 16, 32}", and
   (c) a pipeline reading graph6 from stdin so nauty's geng can stream graphs in.
2. exp_new(title="Erdős–Gyárfás: exhaustive small cubic graphs + spectrum statistics",
   command="geng -c -d3 -D3 14 -q | python scripts/pow2_cycles.py", environment="python-sci",
   run_from="workspace") then exp_run — verify the conjecture exhaustively for all
   connected cubic graphs on up to 14 vertices (record the exact count checked), then
   push n as far as budget allows and record per-n counts and the distribution of
   power-of-2 cycle lengths (which graphs have ONLY 16?).
3. Submit the exhaustive statements as certificates via proof_submit (sympy backend):
   "all N connected cubic graphs on n vertices contain a cycle of length 4, 8 or 16".
   Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a single graph with min degree
$\ge 3$ and no cycle of length any power of 2 — a finite, exactly checkable certificate.
By the structure results, hunt cubic-dominated graphs $\ge 32$ vertices (bipartite:
$\ge 60$): local modifications of the Markström graphs (they miss 4 and 8 already —
destroy the 16-cycles without creating 4/8), girth-6+ cubic graphs from genbg/geng
filtered by spectrum, SAT-guided completion ("no C4/C8/C16/C32" as constraints).
Every candidate must be exactly re-verified (the spectrum routine) and certified via
proof_submit. A verified counterexample claim must name the primary claim in depends_on.

**Proof track.** Reproduce the small-case exhaustion; mine the near-misses (which
structures carry exactly one power-of-2 length; how 16-only graphs distribute);
formulate and test reduction lemmas on the instance zoo ("a minimal counterexample has
no X" — test X against generated graphs); relate to the average-degree theorem (what
happens between average degree 3 and the Liu–Montgomery constant); every unresolved
inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exhaustive verification for small cubic /
min-degree-3 graphs, cycle-spectrum statistics, hard-instance mining around the
Markström graphs, bipartite cubic exhaustion toward the 60-vertex frontier. Instances
can refute (one certified graph suffices); they can never prove the universally
quantified statement.

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
  --statement "For every finite simple graph with minimum degree at least 3, there is a cycle in the graph whose length is a power of 2."
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
