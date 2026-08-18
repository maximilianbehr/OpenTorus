#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The Ryser–Brualdi–Stein conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): MIXED FRONTIER.
# Ryser's statement (odd order => full transversal): OPEN; verified for all
# Latin squares of order <= 9 (McKay-McLeod-Wanless 2006). Brualdi-Stein
# (every order has a partial transversal of size n-1): PROVED for all
# sufficiently large n - regardless of parity - by Montgomery
# (arXiv:2310.19779, 2023; still an unpublished preprint, nonconstructive
# threshold); near transversals verified for ALL orders n <= 11
# (Best-Pula-Wanless, JCD 2021). Prior bounds: n - O(log^2 n) (Hatami-Shor
# 2008), n - O(log n / log log n) (Keevash-Pokrovskiy-Sudakov-Yepremyan 2022).
# Group Cayley tables fully characterized (Hall-Paige, proved 2009).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./ryser_brualdi_stein.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set agent.prove_require_instance_work true  # campaign gate: hold clean completion until instance work exists

# --- 3. Numerical experiment environment ------------------------------------
# Exact-cover / SAT / CP-SAT transversal search, Latin-square generation,
# Cayley-table constructions.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy networkx python-sat ortools
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2310.19779
opentorus paper add https://arxiv.org/abs/2005.00526
opentorus paper add https://arxiv.org/abs/2406.19873

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The Ryser–Brualdi–Stein conjecture

**Primary target (general).** For every integer $n \ge 1$, every $n \times n$ Latin
square has a partial transversal of size $n - 1$, and every Latin square of **odd** order
has a full transversal (a set of $n$ cells, one per row, one per column, one per symbol).
(Ryser 1967 conjectured the odd/full statement; Brualdi and Stein the $n-1$ statement
for all $n$. Even order can genuinely lack full transversals: the Cayley table of
$\mathbb{Z}_{2m}$ has none.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: a
**mixed frontier**, to be reported per statement. (1) The $n-1$ statement is **proved
for all sufficiently large $n$** — regardless of parity — by Montgomery
([arXiv:2310.19779](https://arxiv.org/abs/2310.19779), 2023): "for sufficiently large
$n$, every Latin square of order $n$ has a transversal with $n-1$ cells". The paper's
title says "for large even $n$" because for even $n$ this settles the full conjecture,
while odd $n$ asks for $n$; the result is **still an unpublished preprint** with a
nonconstructive threshold ("there is some $n_0$"), so small $n$ are not covered by it.
Near transversals ARE verified for all orders $n \le 11$ (Best–Pula–Wanless, JCD 29
(2021)). (2) Ryser's odd/full statement is **open**: verified for all Latin squares of
order $\le 9$ (McKay–McLeod–Wanless 2006; minimum transversal counts
$t(3) = t(5) = t(7) = 3$, $t(9) = 68$); Montgomery's own 2024 BCC survey
([arXiv:2406.19873](https://arxiv.org/abs/2406.19873)) says large odd $n$ "would
certainly need new ideas". Prior partial-transversal bounds: $n - O(\log^2 n)$
(Hatami–Shor, JCTA 2008), $n - O(\log n / \log\log n)$
(Keevash–Pokrovskiy–Sudakov–Yepremyan,
[arXiv:2005.00526](https://arxiv.org/abs/2005.00526), Trans. AMS B 2022). Group Cayley
tables are fully characterized: a finite group's table has a full transversal iff its
Sylow 2-subgroups are trivial or non-cyclic (Hall–Paige conjecture, proved 2009 —
Wilcox/Evans/Bray, final step published 2020); groups of order $\equiv 2 \pmod 4$ have
none, and every group-based square has a near transversal (Goddyn–Halasz, JCD 2020).
Attribution note: Ryser's 1967 paper conjectured only the odd/full statement; the
"parity count" version sometimes attributed to him is a misattribution (Best–Wanless,
arXiv:1801.02893) and is false for odd $n$.

**Known partial results (classified, with sources).**
- Montgomery's $n-1$ theorem for large $n$: KNOWN_RESULT with the *preprint* label kept
  visible (no journal yet; nonconstructive threshold).
- KPSY and Hatami–Shor bounds (KNOWN_RESULTs; cite parsed sources).
- Order $\le 9$ full-transversal verification for odd orders and the $t(n)$ minima
  (KNOWN_RESULT; journal-only source — metadata marked, not invented); $n \le 11$ near
  transversals (Best–Pula–Wanless).
- Hall–Paige characterization for groups (KNOWN_RESULT).
- Random Latin squares have full transversals a.a.s. (Kwan) — a neighbor result.

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/transversals.py — (a) an exact transversal finder/counter for a
   given Latin square (exact cover via CP-SAT or python-sat; row/column/symbol
   at-most-one constraints), (b) generators: cyclic-group tables Z_n, elementary-abelian
   tables, random squares via row-by-row completion, and the turn-square family
   (Z_{2m}-based squares with few transversals), and (c) a near-transversal (size n-1)
   checker.
2. exp_new(title="RBS: transversals for small orders and Cayley tables",
   command="python scripts/transversals.py", environment="python-sci",
   run_from="workspace") then exp_run — verify: every Z_n with n odd, n <= 15, has a
   full transversal (and count them); Z_n with n even, n <= 12, has NONE (exact) but
   always a near transversal; random squares of orders 8..12 all have near
   transversals; record transversal-count statistics.
3. Submit each exact fact via proof_submit (sympy backend): "the Cayley table of Z_10
   has no full transversal" (finite exhaustive statement), "square S has a transversal
   T" (explicit witness re-check). Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate either part: (a) an odd-order Latin square with NO full
transversal — order >= 11 by the verification bound; for a FIXED square nonexistence is
a finite exact-cover check, so any candidate is certifiable. Generators: squares with
minimal transversal counts (t(9) = 68 suggests hunting low-count structures), turn-square
analogues of odd order, intercalate-rich squares. (b) A Latin square (any order) with no
partial transversal of size n-1 — order >= 12 by Best-Pula-Wanless, and Montgomery's
theorem confines candidates to below its (unknown, large) threshold; treat as a bounded
search in 12 <= n. A verified counterexample claim must name the primary claim in
depends_on.

**Proof track.** Reproduce the delta-system/absorption vocabulary from the parsed
Montgomery paper at toy scale; certify the Hall-Paige criterion on all groups of order
<= 16 (exhaustive per-group exact checks via proof_submit); mine transversal-count
statistics for structure (what distinguishes low-count squares); every unresolved
inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact transversal counts for small orders,
Cayley-table certificates, near-transversal sweeps, low-count-structure mining.
Instances can refute (one certified square suffices for either part); they can never
prove the all-$n$ statements.

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
  --statement "For every n, every n x n Latin square has a partial transversal of size n-1, and every Latin square of odd order has a full transversal."
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
