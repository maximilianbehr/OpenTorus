#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Seymour's second neighborhood conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): OPEN. Tournaments
# settled (Fisher 1996; Havet-Thomasse 2000 via median orders); general
# constant improved to 0.715538 in Dec 2024 after 20+ years at 0.657
# (Huang-Peng, arXiv:2412.20234); min out-degree <= 6 (Kaneko-Locke 2001),
# delta = 7 computer-assisted 2026 preprint (arXiv:2606.30588); random
# oriented graphs p < 1/2 plus reductions (arXiv:2403.02842, RSA 2025).
# A counterexample needs >= 17 vertices unconditionally (>= 19 modulo the
# unrefereed delta=7 preprint). One unverified full-proof claim exists
# (arXiv:2501.00614) - no peer confirmation.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./second_neighborhood.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# nauty (geng + directg for oriented graphs, gentourng for tournaments; the
# Debian binaries are nauty-prefixed, so symlink them), networkx, CP-SAT/SAT
# for "every vertex violates" encodings.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nauty \
 && rm -rf /var/lib/apt/lists/* \
 && for f in /usr/bin/nauty-*; do ln -sf "$f" "/usr/bin/${f#/usr/bin/nauty-}"; done
RUN pip install --no-cache-dir numpy sympy networkx python-sat ortools
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/2412.20234
opentorus paper fetch https://arxiv.org/abs/2606.30588
opentorus paper fetch https://arxiv.org/abs/2403.02842

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Seymour's second neighborhood conjecture

**Primary target (general).** For every oriented graph (a digraph with no loops, no
digons, no parallel arcs) there is a vertex $v$ with $|N^{++}(v)| \ge |N^{+}(v)|$, where
$N^{+}(v)$ is the out-neighborhood and $N^{++}(v)$ the set of vertices at directed
distance exactly 2 from $v$. (Seymour, 1990. The digon-free hypothesis is essential —
with 2-cycles the statement is false.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
One full-proof claim on arXiv (Glover, arXiv:2501.00614, v14 May 2026) has no journal
acceptance and no independent confirmation — record it as claimed/unverified. A 2026
preprint's "counterexamples" (arXiv:2601.21563, withdrawn v4) refuted the author's own
auxiliary conjecture, not Seymour's. Settled classes: tournaments (Fisher 1996, Dean's
conjecture; Havet–Thomassé 2000 via median orders — with *two* Seymour vertices when no
vertex is dominated); tournaments minus a matching / minus a star, min degree $n-2$
(Fidler–Yuster 2007); quasi-transitive (Gutin–Li, arXiv:1704.01389); further
star-removal classes (arXiv:2406.03635). General constant: some vertex has
$|N^{++}| \ge \gamma |N^{+}|$ with $\gamma = 0.657298$ (Chen–Shen–Yuster 2003; the root
of $2x^3 + x^2 = 1$), improved after 20+ years to $0.715538$ (Huang–Peng,
[arXiv:2412.20234](https://arxiv.org/abs/2412.20234)). Minimum out-degree: true for
$\delta^+ \le 6$ (Kaneko–Locke 2001); $\delta^+ = 7$ computer-assisted
(Sadhukhan–Sandeep–Sen, [arXiv:2606.30588](https://arxiv.org/abs/2606.30588), CP-SAT,
2026 preprint). Random/dense: all orientations of $G(n,p)$ for $p < 1/2$, with
reductions showing counterexamples (if any) yield arbitrarily large strongly connected
ones with bounded $\delta^+$, and vertex-minimal ones have large min degree
(Espuny Díaz–Girão–Granet–Kronenberg,
[arXiv:2403.02842](https://arxiv.org/abs/2403.02842), RSA 2025); Seymour-tight
orientations (arXiv:2603.29626); the $n = 2\delta + 2$ case (arXiv:2608.11530). A
counterexample needs $\ge 17$ vertices unconditionally ($\ge 19$ modulo the unrefereed
$\delta^+ = 7$ preprint). SNC implies the Caccetta–Häggkvist special case with minimum
in- AND out-degree $\ge n/3$; the converse implication does not hold.

**Known partial results (classified, with sources).**
- Tournaments and the star/matching-removal classes (KNOWN_RESULTs; the Havet–Thomassé
  two-vertex form only under the no-dominated-vertex hypothesis).
- The 0.657298 and 0.715538 constants (KNOWN_RESULT; arXiv:2412.20234 — take the exact
  statement from the parsed paper).
- $\delta^+ \le 6$ (Kaneko–Locke; journal-only — mark metadata honestly) and the
  $\delta^+ = 7$ preprint (CLAIMED/computer-assisted; unrefereed — keep the layer
  separate).
- Random-orientation results and the minimal-counterexample reductions
  (arXiv:2403.02842).
- Glover's proof claim: CLAIMED, unverified — never a KNOWN_RESULT.

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/seymour_check.py — (a) exact $|N^+|, |N^{++}|$ per vertex for a
   digraph, the Seymour-vertex set, and the margin $\min_v (|N^{++}(v)| - |N^+(v)|)$;
   (b) a graph6/digraph6 stdin pipeline so nauty (geng | directg -o) can stream all
   oriented graphs of order n.
2. exp_new(title="Seymour: exhaustive small oriented graphs",
   command="geng 7 -q | directg -o -q | python scripts/seymour_check.py",
   environment="python-sci", run_from="workspace") then exp_run — verify the conjecture
   exhaustively for all oriented graphs on up to 7 vertices (record exact counts),
   tournaments to 9 (gentourng), and record Seymour-vertex statistics (how many, which
   margins, which graphs are tight).
3. Submit the exhaustive statements via proof_submit (sympy backend): "all N oriented
   graphs on n vertices contain a Seymour vertex". Only ACCEPTED submissions are
   machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is one oriented graph where EVERY vertex
has $|N^{++}(v)| < |N^{+}(v)|$ — finite and exactly checkable. The known bounds say:
$\ge 17$ vertices, large minimum out-degree ($\ge 8$ modulo the preprint), and the
reductions point at near-regular, dense, strongly connected candidates (Seymour-tight
orientations, tournament-minus-few-edges structures). Encode "every vertex violates" as
CP-SAT/SAT with reachability indicators and search orders 17–20 under symmetry-breaking
and degree constraints; any hit must be exactly re-verified by the spectrum script and
certified via proof_submit. A verified counterexample claim must name the primary claim
in depends_on.

**Proof track.** Reproduce the median-order argument on generated tournaments (exact
checks of the two-vertex statement under its hypothesis); verify the 0.657/0.7155
constants on the instance zoo (is the bound tight anywhere small?); test candidate
reduction lemmas against exhaustive data ("a minimal counterexample has min out-degree
$\ge 8$", "is strongly connected", ...); every unresolved inference is an explicit
[GAP-n].

**Instance program (tools, not targets).** Exhaustive small-order verification,
Seymour-vertex statistics, margin distributions, tight-instance mining, bounded SAT
searches in the 17–20 vertex window. Instances can refute (one certified digraph
suffices); they can never prove the universally quantified statement.

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
  --statement "For every oriented graph (no loops, digons, or parallel arcs) there is a vertex whose second out-neighborhood is at least as large as its first out-neighborhood."
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
opentorus problem report "${TARGET}" --lint
opentorus problem verdict "${TARGET}"
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
