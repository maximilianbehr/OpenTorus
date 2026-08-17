#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The 1/3–2/3 conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): OPEN. Verified
# through n = 14 by a census of all 1,338,193,159,771 posets (Gupta,
# arXiv:2607.23926, Jul 2026; previous frontiers n <= 13 De Loof et al. 2010,
# n <= 11 Peczarski 2006). Best general constant: (5-sqrt(5))/10 ~ 0.2764
# (Brightwell-Felsner-Trotter 1995), after Kahn-Saks 3/11 (1984). Settled:
# width 2 (Linial 1984; sharpened Sah 2021), semiorders (Brightwell 1989),
# height 2 (TGF 1992), 6-thin (Peczarski 2008), series-parallel/N-free
# (Zaguia), forests, several lattice families (Olson-Sagan). Width 3 open.
# 1/3 is tight exactly for ordinal sums of singletons and the 3-element V.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./one_third_two_thirds.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# nauty's genposetg (Debian package; nauty-prefixed binaries are symlinked)
# generates posets up to isomorphism; linear extensions are counted exactly by
# DP over order ideals; sympy Fractions certify the balance ratios.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nauty \
 && rm -rf /var/lib/apt/lists/* \
 && for f in /usr/bin/nauty-*; do ln -sf "$f" "/usr/bin/${f#/usr/bin/nauty-}"; done
RUN pip install --no-cache-dir numpy sympy networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2607.23926
opentorus paper add https://arxiv.org/abs/1811.01500
opentorus paper add https://arxiv.org/abs/2311.02743

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The 1/3–2/3 conjecture

**Primary target (general).** For every finite partially ordered set that is not totally
ordered, there is a pair of elements $x, y$ such that the fraction of linear extensions
in which $x$ precedes $y$ lies in $[1/3, 2/3]$. (Kislitsyn 1968; independently Fredman
1976 and Linial 1984. Equivalently: the balance constant
$\delta(P) = \max_{x,y} \min\{\Pr[x \prec y], \Pr[y \prec x]\} \ge 1/3$ for every finite
non-chain poset $P$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
Verified exhaustively through $n = 14$: a census of all $1{,}338{,}193{,}159{,}771$
unlabeled 14-element posets confirms the Gold Partition Conjecture — and hence 1/3–2/3 —
through 14 (Gupta, [arXiv:2607.23926](https://arxiv.org/abs/2607.23926), Jul 2026, with
code and data; previous frontiers: $n \le 13$, De Loof–De Baets–De Meyer 2010;
$n \le 11$ via GPC, Peczarski 2006). Best general bound: every non-chain poset has
$\delta(P) \ge (5 - \sqrt 5)/10 \approx 0.2764$ (Brightwell–Felsner–Trotter, Order 12
(1995), tight for their infinite-poset extension), after Kahn–Saks $3/11$ (1984) and
Kahn–Linial $1/(2e)$ (1991). Settled classes: width 2 (Linial 1984; sharpened to
$\delta \ge (-3 + 5\sqrt{17})/52 \approx 0.33876$ unless an ordinal sum of singletons
and $C_2 + C_1$ — Sah, Combinatorica 41 (2021),
[arXiv:1811.01500](https://arxiv.org/abs/1811.01500)); semiorders (Brightwell 1989);
height 2 (Trotter–Gehrlein–Fishburn 1992); posets with a nontrivial automorphism
(Ganter–Hafner–Poguntke 1987); 5-thin (Brightwell–Wright 1992) and 6-thin (Peczarski
2008); series-parallel and N-free (Zaguia 2012); posets whose cover graph is a forest
(Zaguia 2019); Boolean, set-partition and subspace lattices, Young-diagram posets
(Olson–Sagan 2018); many minimal elements / dense posets (Friedman 1993). **Width 3 is
open** — the smallest known width-3 balance is $14/39$ (Saks 1985). Asymptotics:
$\delta(P) \to 1/2$ for width $\Omega(n)$ or $\omega(\log n)$ minimal elements;
$\delta \ge 1/e - o(1)$ for width $\omega(\sqrt n)$ (Aires–Kahn, arXiv:2509.11549).
Tightness: $\delta = 1/3$ is attained exactly (as far as known) by ordinal sums of
singletons and copies of $T$ = (2-chain + isolated point) — all width 2; through
$n = 14$ these are the only extremal classes ($a(n) - 1$ non-chain classes at $n = 14$:
128), and the least balance above 1/3 is $37/106$; Peczarski conjectures a gap
($\delta \ne 1/3 \Rightarrow \delta \gtrsim 0.3488$), Chen's family approaches
$\approx 0.3489$ from above (arXiv:1709.05753). Terminology alert: the Chan–Pak survey
([arXiv:2311.02743](https://arxiv.org/abs/2311.02743), EMS Surv. 2025) uses the *sorting
probability* $\min|\Pr[x \prec y] - \Pr[y \prec x]| \le 1/3$ — the same conjecture,
opposite normalization.

**Known partial results (classified, with sources).**
- The settled classes above (KNOWN_RESULTs; cite parsed sources; keep the width-2
  exceptional family exact).
- The census through $n = 14$ (KNOWN_RESULT; 2026 preprint with published code/data —
  label the preprint status).
- BFT constant and Kahn–Saks 3/11 (KNOWN_RESULTs; journal-only sources are marked, not
  reconstructed).
- Width 3 open, $14/39$ record; the gap conjecture and Chen's family (CONJECTURE layer).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/balance.py — (a) exact linear-extension pair counts by DP over
   order ideals (bitmask over antichains; De Loof-style forward/backward pass giving
   all Pr[x < y] as exact Fractions), (b) delta(P) and the witness pair, and (c) a
   digraph6 stdin pipeline so genposetg -o can stream Hasse diagrams in.
2. exp_new(title="1/3-2/3: exhaustive census for small n",
   command="genposetg -o 7 -q | python scripts/balance.py", environment="python-sci",
   run_from="workspace") then exp_run — verify the conjecture exhaustively for all
   posets on up to 7 elements (record exact counts; A000112: 2045 posets at n=7),
   push to 8 (16999) or 9 (183231) as budget allows; record the delta histogram, the
   delta = 1/3 classes (check: ordinal sums of singletons and T only), and the minimal
   delta > 1/3 per n; cross-check the width-3 minimum 14/39 at n = 7.
3. Submit the per-n exhaustive statements via proof_submit (sympy backend): "every
   non-chain poset on n elements has a pair with extension ratio in [1/3, 2/3]" (as an
   exact finite computation over the enumerated isomorphism classes). Only ACCEPTED
   submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a single finite non-chain poset with
$\delta(P) < 1/3$ — finite and exactly checkable (linear-extension counting is exact).
The census says $n \ge 15$; structure results say width $\ge 3$, no nontrivial
automorphism, not series-parallel/N-free, cover graph not a forest, height $\ge 3$.
Search: width-3 towers and grids beyond the settled families, lexicographic-sum
compositions that dodge the GPC closure, local search minimizing delta with exact
re-evaluation. Any candidate is certified via proof_submit. A verified counterexample
claim must name the primary claim in depends_on.

**Proof track.** Reproduce the extremal classification through the census range; test
the gap conjecture on the zoo (is 37/106 beaten at n = 15 samples?); test candidate
lemmas ("delta is monotone under X", GPC instances) against generated posets; relate the
width-2 sharpening to the width-3 frontier; every unresolved inference is an explicit
[GAP-n].

**Instance program (tools, not targets).** Exhaustive small-n verification with exact
rational certificates, delta histograms, extremal-class census, width-3 record mining.
Instances can refute (one certified poset suffices); they can never prove the
universally quantified statement.

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
  --statement "For every finite partially ordered set that is not totally ordered, there is a pair x, y such that the fraction of linear extensions with x before y lies in [1/3, 2/3]."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
opentorus --verbose prove "${TARGET}" --min-papers 5

# --- 8. Honest report, verdict, PDF ------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint
opentorus problem verdict "${TARGET}"
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
