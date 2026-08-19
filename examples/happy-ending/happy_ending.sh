#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Erdős–Szekeres "happy ending" conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): OPEN. Exact values
# ES(4)=5 (Klein), ES(5)=9, ES(6)=17 (Szekeres-Peters 2006, ~1500 CPU-h;
# SAT re-verifications by Maric 2019 (Isabelle), Scheucher (~1 CPU-h),
# Heule-Scheucher 2024 (8.53 CPU-s)); ES(7)=33 open (anchored-subfamily UNSAT
# certificates only, arXiv:2512.24061). Upper bounds: Suk 2^{n+O(n^{2/3}log n)}
# (arXiv:1604.08657, JAMS 2017), Holmsen-Mojarrad-Pach-Tardos
# 2^{n+O(sqrt(n log n))} (arXiv:1710.11415, JEMS 2020) - still the best.
# Baek-Balko (SoCG 2025/JCTA 2026): split k-gons at 2^{k-2}+1 (tight).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./happy_ending.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact orientation tests (integer arithmetic), SAT over signotope axioms
# (python-sat), convex-position checks of explicit constructions.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy networkx python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/1604.08657
opentorus paper fetch https://arxiv.org/abs/1710.11415
opentorus paper fetch https://arxiv.org/abs/2403.00737

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Erdős–Szekeres "happy ending" conjecture

**Primary target (general).** For every integer $n \ge 3$, every set of $2^{n-2} + 1$
points in general position in the plane contains $n$ points in convex position — i.e.
$ES(n) = 2^{n-2} + 1$, where $ES(n)$ is the least $N$ such that every $N$ points in
general position contain a convex $n$-gon. (Erdős–Szekeres; the lower-bound
construction with $2^{n-2}$ points and no convex $n$-gon is Erdős–Szekeres 1960/61.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**
(Erdős problem #107; \$500 for a proof, \$1000 offered by Graham). Exact values:
$ES(3) = 3$; $ES(4) = 5$ (Klein — dating varies between 1931 and 1932/33 across
sources); $ES(5) = 9$ (Makai, unpublished, cited 1935; first published proof
Kalbfleisch–Kalbfleisch–Stanton 1970); $ES(6) = 17$ (Szekeres–Peters 2006,
~1500 CPU-hours), re-verified by SAT far cheaper: Marić 2019 (SAT + Isabelle/HOL),
Scheucher (~1 CPU-hour, arXiv:1807.10848), and the Heule–Scheucher encoding
([arXiv:2403.00737](https://arxiv.org/abs/2403.00737)) re-derives it in 8.53 CPU-s.
$ES(7) = 33$ is open: the stronger Peters–Szekeres conjecture was SAT-refuted
(Balko–Valtr 2017), and current work reaches UNSAT certificates only for
convex-layer-anchored subfamilies of 33-point sets (Dumitru, arXiv:2512.24061,
Dec 2025). General bounds: lower $2^{n-2} + 1$; upper
$\binom{2n-4}{n-2} + 1$ (Erdős–Szekeres 1935), $2^{n + O(n^{2/3}\log n)}$ (Suk,
[arXiv:1604.08657](https://arxiv.org/abs/1604.08657), JAMS 2017),
$2^{n + O(\sqrt{n \log n})}$ (Holmsen–Mojarrad–Pach–Tardos,
[arXiv:1710.11415](https://arxiv.org/abs/1710.11415), JEMS 2020, also for
pseudo-configurations) — still the best. Recent: "split $k$-gons" appear at
$2^{k-2} + 1$ points (tight), and the conjecture holds for "decomposable" sets
(Baek–Balko, SoCG 2025 / JCTA 2026). Related but distinct: the empty-hexagon number
$h(6) = 30$ (Heule–Scheucher, arXiv:2403.00737; Lean-verified pipeline
arXiv:2403.17370) — the *holes* problem, not $ES(n)$.

**Known partial results (classified, with sources).**
- Exact values $ES(3..6)$ (KNOWN_RESULTs; the $ES(6)$ verifications double as a METHOD
  anchor: order-type/signotope SAT encodings).
- Suk and HMPT upper bounds (KNOWN_RESULTs; cite parsed sources).
- The $2^{n-2}$-point lower-bound constructions (KNOWN_RESULT; explicitly checkable).
- Balko–Valtr refutation of the Peters–Szekeres strengthening; Dumitru's anchored
  subfamily certificates (partial, not ES(7)); Baek–Balko split-polygon theorem.

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/es_tools.py — (a) an exact convex-position/convex-n-gon detector
   over integer coordinates (orientation determinants, integer arithmetic, no floats),
   (b) an Erdős–Szekeres lower-bound construction generator for n = 5, 6, 7 (the
   2^{n-2}-point sets), and (c) a signotope-axiom SAT encoder: triple orientation
   variables, 4-point signotope axioms, "no convex k-gon" constraints, emitting DIMACS.
2. exp_new(title="Happy ending: constructions and ES(6) re-verification",
   command="python scripts/es_tools.py", environment="python-sci",
   run_from="workspace") then exp_run — verify exactly that the generated 8-, 16- and
   32-point constructions contain no convex 5-, 6-, 7-gon respectively, and re-derive
   ES(6) = 17 abstractly: UNSAT for "17 points, signotope axioms, no convex hexagon"
   (record solver time and the certificate).
3. Submit each exact fact via proof_submit (sympy backend for the finite convex-position
   checks): "this explicit 32-point set contains no convex heptagon". Only ACCEPTED
   submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a set of $2^{n-2} + 1$ points in
general position with NO convex $n$-gon, for some $n$ — first candidate $n = 7$:
33 points without a convex heptagon. Search: SAT on the abstract level (33 points,
signotope axioms, no convex 7-gon) — a SAT witness is an *abstract order type* and must
additionally be realized by integer coordinates (realizability is the hard second step;
record abstract witnesses honestly as abstract). Local search over integer point sets
(perturbations of the 32-point construction). Any realized candidate is exactly
checkable and certified via proof_submit. A verified counterexample claim must name the
primary claim in depends_on.

**Proof track.** Reproduce ES(6) = 17 via the SAT encoding (UNSAT + certificate);
attack anchored subfamilies of the 33-point problem as LEMMAs (convex-layer structures
à la Dumitru); mine the constructions for the structural reason the $2^{n-2}$ bound is
tight; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact construction checks, the ES(6)
re-verification, anchored-subfamily UNSAT runs, order-type statistics. Instances can
refute (a realized 33-point witness would disprove $ES(7) = 33$ and hence the
conjecture); they can never prove the all-$n$ statement.

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
  --statement "For every integer n >= 3, every set of 2^(n-2) + 1 points in general position in the plane contains n points in convex position; equivalently ES(n) = 2^(n-2) + 1."
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
