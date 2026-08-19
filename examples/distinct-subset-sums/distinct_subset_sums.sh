#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Erdős' distinct subset sums conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): OPEN (Erdős
# Problem #1, $500). Best lower bound Theta(2^n/sqrt n): max A >= C(n, n/2)
# exactly and (sqrt(2/pi) - o(1)) 2^n / sqrt n asymptotically (Dubroff-Fox-Xu,
# arXiv:2006.12988; the constant is also Elkies-Gleason's). Best constructions:
# Conway-Guy 1967, Lunnon 1988, Bohman 1998 (0.22002 * 2^n for large n).
# Exact minima known for n <= 10 (OEIS A276661; a(10) = 309, Dyson 2025).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./distinct_subset_sums.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact subset-sum checks (bitsets / sympy), CP-SAT and SAT for minimal-maximum
# searches at small n, mpmath for the analytic constants.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy mpmath ortools python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/2006.12988
opentorus paper fetch https://arxiv.org/abs/2208.12182
opentorus paper fetch https://arxiv.org/abs/math/0503115

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Erdős' distinct subset sums conjecture

**Primary target (general).** There is a universal constant $c > 0$ such that for every
$n$ and every set $A = \{a_1 < \dots < a_n\}$ of positive integers whose $2^n$ subset sums
are pairwise distinct, $\max A \ge c \cdot 2^n$. (Erdős, 1930s; Erdős Problem #1, \$500.
Powers of two show $\max A = 2^{n-1}$ is attainable, so $c \le 1/2$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check:
**open**. Erdős Problem #1 lists it open with no accepted proof; a 2025 self-published
(non-arXiv, unrefereed) "resolution" exists and is not recognized — record it as an
unverified claim only. Best lower bounds are all of order $2^n/\sqrt{n}$: Erdős–Moser
1955 gave $(1/4 - o(1))\,2^n/\sqrt n$; the constant was improved through Alon–Spencer,
Elkies, Guy/Bae, Aliev $\sqrt{3/(2\pi)}$
([arXiv:math/0503115](https://arxiv.org/abs/math/0503115)) to $\sqrt{2/\pi}$
(Elkies–Gleason, unpublished; Dubroff–Fox–Xu,
[arXiv:2006.12988](https://arxiv.org/abs/2006.12988), who also prove the exact bound
$\max A \ge \binom{n}{\lfloor n/2\rfloor}$ for every $n$); Steinerberger
([arXiv:2208.12182](https://arxiv.org/abs/2208.12182)) reproves $\sqrt{2/\pi}$
analytically. Best upper bounds (constructions): Conway–Guy 1967 (OEIS A005318; all
Conway–Guy sets are sum-distinct — Bohman 1996), Lunnon 1988 ($0.22096\cdot 2^n$),
Bohman 1998 ($0.22002 \cdot 2^n$ for $n$ sufficiently large — still the record). Exact
minima $a(n)$ of $\max A$ (OEIS A276661): $1, 2, 4, 7, 13, 24, 44, 84, 161, 309$ for
$n = 1..10$ ($n \le 8$ Lunnon 1988; $a(9) = 161$ Grossman 2016; $a(10) = 309$ Dyson,
Oct 2025, exhaustive, unique optimal set
$\{148, 225, 265, 285, 296, 302, 305, 307, 308, 309\}$); $a(11) \le 594$ (Conway–Guy),
$a(12) \le 1157$, $a(13) \le 2249$ (Popov 2025), all unsettled. The gap between
$2^n/\sqrt n$ and $c\,2^n$ is the whole problem.

**Known partial results (classified, with sources).**
- $\max A \ge \binom{n}{\lfloor n/2\rfloor}$ for every $n$, and
  $\ge (\sqrt{2/\pi} - o(1))\,2^n/\sqrt n$ — Dubroff–Fox–Xu (KNOWN_RESULT; arXiv:2006.12988).
- $\sqrt{3/(2\pi)}$ constant — Aliev (KNOWN_RESULT; arXiv:math/0503115).
- Conway–Guy sets are sum-distinct — Bohman 1996 (KNOWN_RESULT; cite the parsed source
  or mark the journal-only source as such).
- Bohman 1998: $\max A < 0.22002 \cdot 2^n$ for large $n$ (KNOWN_RESULT; journal-only —
  metadata marked missing if not fetched, never invented).
- Exact $a(n)$ for $n \le 10$ (KNOWN_RESULT with explicit sets; OEIS A276661).
- Modular variant (Cambie–Gao–Kim–Liu, arXiv:2308.03748) — a neighbor, not the target.

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/subset_sums.py — (a) an exact sum-distinctness checker for a given
   integer set (bitset of achievable sums; integers only), (b) the Conway–Guy generator
   $u_{n+1} = 2u_n - u_{n-r}$, $r = \lfloor 1/2 + \sqrt{2n}\rfloor$, with the derived
   sets, and (c) an exact branch-and-bound / CP-SAT search for the minimal $\max A$ for
   $n \le 8$ (reproduce $a(n)$).
2. exp_new(title="Distinct subset sums: exact minima and record sets",
   command="python scripts/subset_sums.py", environment="python-sci",
   run_from="workspace") then exp_run — record $a(n)$ for $n \le 8$ (or the bound you
   reached), verify the $n = 9, 10$ optimal sets and the Conway–Guy sets up to $n = 40$,
   and tabulate $a(n)/2^n$ against $\binom{n}{\lfloor n/2\rfloor}/2^n$.
3. Submit each exact fact as a certificate via proof_submit (sympy backend): "the set S
   has pairwise distinct subset sums" and "no set of n positive integers with max < a(n)
   has distinct subset sums" (the latter only if your search was exhaustive and you can
   state it as a finite check). Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: the conjecture fails iff $a(n)/2^n \to 0$, i.e. there are
sum-distinct sets with $\max A = o(2^n)$. A single finite set can never refute a
universal-constant statement — but a *family* with a certified decay rate would. Search:
CP-SAT / SAT for sum-distinct sets with small maximum at $n = 11..14$ (beat 594, 1157,
2249 — a certified new record is a first-class result even though it refutes nothing);
structured generators (Conway–Guy variants, Lunnon's recurrences, greedy-plus-repair).
Every candidate must be exactly re-verified and certified via proof_submit. A verified
counterexample claim must name the primary claim in depends_on.

**Proof track.** Reproduce the second-moment (Erdős–Moser) argument and the
Dubroff–Fox–Xu binomial bound as certified finite checks where possible (the inequality
$a(n) \ge \binom{n}{\lfloor n/2\rfloor}$ for the known $a(n)$ is exact); mine the exact
minimizers ($n \le 10$) for structure (near-doubling tails, distances between elements,
Conway–Guy-likeness); test candidate lemmas ("every optimal set has $a_n - a_{n-1} \le 2$",
etc.) against the instance zoo; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact minima for small $n$, record
constructions, and the ratio table $a(n)/2^n$ (still decreasing at $n = 10$: $0.3018$).
Instances can certify constructions and small-$n$ optima; they can never prove or
refute a statement about a universal constant.

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
  --statement "There is a universal constant c > 0 such that for every n and every set of n positive integers with pairwise distinct subset sums, the maximum element is at least c * 2^n."
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
