#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Frankl's union-closed sets conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-14, amended 2026-08-15 after peer cross-check: OPEN.
# Constant lower bounds since Gilmer (2022, 0.01); days later independently
# improved to (3-sqrt(5))/2 ~ 0.38197 (Alweiss-Huang-Sellke arXiv:2211.11731;
# Chase-Lovett arXiv:2211.11689; Sawin arXiv:2211.11504), refined to ~0.3824
# (Cambie, arXiv:2212.12500); current record ~0.38271 (Liu, arXiv:2306.08824)
# relies partly on numerically verified hypotheses. Chase-Lovett: (3-sqrt(5))/2
# is OPTIMAL for the approximate version — new ideas needed for 1/2. Sporadic
# claimed proofs circulate without community acceptance; the literature phase
# must re-check.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./frankl.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted
opentorus config set campaign.branch_step_budget "${OPENTORUS_BRANCH_STEPS:-40}"
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exhaustive/SAT search over union-closed families (small ground sets), abundance
# statistics, entropy-bound reproductions; z3 for bounded refutation encodings.
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
opentorus paper fetch https://arxiv.org/abs/2211.11689
opentorus paper fetch https://arxiv.org/abs/2211.11731
opentorus paper fetch https://arxiv.org/abs/2212.12500

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Frankl's union-closed sets conjecture

**Primary target (general).** For every finite union-closed family F of finite sets with
F not equal to {emptyset}, there exists an element x that belongs to at least half of the
members of F.

**Status audit (2026-08-14; amended 2026-08-15 after an independent cross-check).**
Fresh web check at creation: **open** in general. The
Gilmer line (2022–2023) gives constant lower bounds: Gilmer proved a 0.01 fraction via an
entropy/information argument; within days, independent preprints improved this to
$(3-\sqrt5)/2 \approx 0.38197$ (Alweiss–Huang–Sellke
[arXiv:2211.11731](https://arxiv.org/abs/2211.11731); Chase–Lovett
[arXiv:2211.11689](https://arxiv.org/abs/2211.11689); Sawin
[arXiv:2211.11504](https://arxiv.org/abs/2211.11504)), refined to
$\approx 0.3824$ (Cambie, [arXiv:2212.12500](https://arxiv.org/abs/2212.12500)); the
current record $\approx 0.38271$ (Liu, arXiv:2306.08824) relies in part on numerically
verified hypotheses, so $\approx 0.3824$ remains the fully rigorous bound. Chase–Lovett showed
$(3-\sqrt5)/2$ is **optimal for the approximate version** (approximately-union-closed
families), so reaching $1/2$ needs genuinely new ideas. Sporadic claimed full proofs
circulate without community acceptance; re-check during the literature phase and classify
any such claim as claimed/unreviewed.

**Known partial results (classified, with sources).**
- Constant abundance $\ge (3-\sqrt5)/2$ for all union-closed families — Gilmer line,
  arXiv:2211.11689 and successors (KNOWN_RESULT with source).
- $(3-\sqrt5)/2$ optimal for approximately-union-closed families — Chase–Lovett
  (KNOWN_RESULT; explains the barrier, does NOT bound the true conjecture away from 1/2).
- Verified for families with small ground set / few sets (classical exhaustive results;
  cite what the literature phase parses — no number from memory).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/uc_families.py — generate union-closed families (close random
   seed families under union), compute EXACT per-element abundance (fractions, no
   floats), report the maximum abundance and the argmax element.
2. exp_new(title="Abundance minima over union-closed families",
   command="python scripts/uc_families.py", environment="python-sci",
   run_from="workspace") then exp_run — exhaustive over ground sets of size <= 4,
   plus biased low-abundance search on sizes 5-8.
3. For each extremal family found, submit an exact certificate via proof_submit
   (sympy backend): "family F (listed) is union-closed and its maximum abundance is
   exactly a/b". Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a finite union-closed family $F \ne
\{\emptyset\}$ in which every element belongs to fewer than $|F|/2$ members. Generators:
random union-closed closures of seed sets, lattice-theoretic constructions (union-closed
families = join-semilattices), low-abundance-biased local search. Search: exhaustive over
tiny ground sets, SAT/z3 encodings (element-membership matrix + closure constraints +
abundance < 1/2), simulated annealing on closures. Minimize candidates; re-verify
independently; a candidate is a finite certificate — exact abundance recount via sympy,
submitted through proof_submit. A verified counterexample claim must name the primary
claim in depends_on.

**Proof track.** Reproduce the entropy bound computationally on generated families (the
inequality chain is checkable per family); minimal-counterexample reductions (known
structural constraints on a hypothetical counterexample); mine abundance-distribution
invariants from exact enumerations; test candidate sharpenings of the Gilmer functional
against the family zoo, formalizing finite lemma instances via proof_submit (sympy);
assemble the dependency graph; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exhaustive family enumeration for ground sets
of size <= 5-6 (exact abundance statistics, extremal profiles near 1/2), SAT-driven
low-abundance search on larger grounds, entropy-functional evaluations. Instances can
refute (one verified family suffices) but can never prove the general statement — they
feed lemma candidates only.

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
  --statement "For every finite union-closed family F of finite sets with F != {emptyset}, there exists an element x that belongs to at least half of the members of F."
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
