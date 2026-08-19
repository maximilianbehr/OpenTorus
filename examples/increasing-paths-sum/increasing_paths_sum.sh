#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Increasing paths in edge orderings: the
#                              Chung–Graham sum conjecture sum_v t(v) >= |E|
#                              (and Graham's altitude question f(K_n) >= cn)
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Graph Ramsey theory" (AIM workshop Jan 26-30,
#         2015, org. Conlon, Fox, Mubayi), Problem 1.38 [Ron Graham];
#         http://aimpl.org/graphramsey/1/ (http only).
# Status audit 2026-08-17 (independently counter-checked): both questions
# OPEN. Altitude of K_n: n^{1-o(1)} <= f(K_n) <= (1/2+o(1))n (Bucic-Kwan-
# Pokrovskiy-Sudakov-Tran-Wagner 2018/2020; Calderbank-Chung-Sturtevant
# 1984) - no c > 0 is proved. The sum question, due to Chung and Graham, is
# stronger (it implies f(K_n) >= (n-1)/2), restated open in Bucic et al.'s
# concluding remarks; the trail version is solved (Graham-Kleitman) and
# Winkler's token argument gives sum of trail lengths = 2|E|, which does NOT
# settle the path version. Exact values f(K_3..K_6) = 2, 2, 3, 4 and min
# sum_v t(v) = 5, 8, 14, 20 for K_3..K_6 were computed at creation, twice,
# independently; no graph on <= 6 vertices violates the sum conjecture.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./increasing_paths_sum.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# nauty geng (Debian package; nauty-prefixed binaries symlinked) to stream
# graphs; gcc for exhaustive / branch-and-bound searches over edge orderings
# (Python is too slow beyond |E| ~ 10); CP-SAT for "no increasing path of
# length L" models.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nauty gcc libc6-dev \
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
opentorus paper fetch https://arxiv.org/abs/1809.01468
opentorus paper fetch https://arxiv.org/abs/1509.02143
opentorus paper fetch https://arxiv.org/abs/1502.03146
opentorus paper fetch https://arxiv.org/abs/1605.07204

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Increasing paths in edge orderings — the Chung–Graham sum conjecture

**Primary target (general).** For every finite graph $G$ and every labelling of its edges
by $1, 2, \dots, |E(G)|$ (a bijection), let $t(v)$ be the length (number of edges) of the
longest increasing path starting at $v$ — a *path*: distinct vertices, labels strictly
increasing along it. Then
$$\sum_{v \in V(G)} t(v) \;\ge\; |E(G)|.$$
(AIM graphramsey Problem 1.38 [Ron Graham], second question, verbatim: "is it true that
for any graph $G$, edges labeled $1, 2, \dots, |E(G)|$, we always have
$\sum_{v \in V(G)} t(v) \ge |E(G)|$?" — a question of Chung and Graham. The first question
on the page, "Is it true that $\max_v t(v) \ge cn$ for some $c > 0$?" for $K_n$, is the
altitude problem $f(K_n) = \Omega(n)$; the sum conjecture implies it with
$f(K_n) \ge (n-1)/2$, so proving the altitude question does *not* prove the primary
target, and the primary target is the stronger, universally quantified statement.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **both
open**. Altitude of $K_n$ ($f(G) = \min_{\text{orderings}} \max_v t(v)$): Graham–Kleitman
(1973) $\sqrt{n - 3/4} - 1/2 \le f(K_n) \le 3n/4$ and the *trail* version solved (an
increasing trail of length $n-1$ always exists, $n$ for $n \in \{3, 5\}$; every $n$-vertex
graph has an increasing trail of length $\ge 2|E|/n$ — Winkler's token proof); Rödl (1973)
$f(K_n) \le (2/3 + o(1))n$; Alspach–Heinrich–Graham $(7/12 + o(1))n$; Calderbank–Chung–
Sturtevant (1984) $(1/2 + o(1))n$, conjectured tight; Milans
([arXiv:1509.02143](https://arxiv.org/abs/1509.02143)) $\Omega((n/\log n)^{2/3})$;
Bucić–Kwan–Pokrovskiy–Sudakov–Tran–Wagner
([arXiv:1809.01468](https://arxiv.org/abs/1809.01468), Israel J. Math. 2020)
$f(K_n) \ge n^{1 - o(1)}$ (the question goes back to Chvátal–Komlós 1971; the
previous record was $n^{2/3 - o(1)}$) and, for general $n$-vertex graphs of average
degree $d$, a monotone path of length $d / 2^{O(\sqrt{\log d \log\log n})}$ — which is
$d^{1-o(1)}$ only for $d = (\log n)^{\omega(1)}$; their concluding remarks ask for
$\Omega(n)$, "or even
$(1/2 - o(1))n$?", and restate the Chung–Graham sum question as open (also on West's REGS
page). $n^{1-o(1)}$ is **not** $\Omega(n)$: no $c > 0$ is proved. Random orderings:
increasing path of length $\ge 0.85n$ w.h.p. and Hamiltonian with probability $\ge 1/e$
(Lavrov–Loh, arXiv:1403.0948), Hamiltonian w.h.p. (Martinsson,
[arXiv:1605.07204](https://arxiv.org/abs/1605.07204)); hypercube and random graphs: De
Silva–Molla–Pfender–Retter–Tait ([arXiv:1502.03146](https://arxiv.org/abs/1502.03146));
$f(G) \le \Delta + 1$; planar $f \le 9$ (Roditty–Shoham–Yuster 2001). Exact $f(K_n)$ is
known only for $n \le 8$ (Burger–Cockayne–Mynhardt, Australas. J. Combin. 31 (2005)).
No 2024–2026 progress on either question (arXiv sweep of edge-ordered Ramsey/Turán/
saturation work — none bears on $f(K_n)$ or the sum). The page's "$\sqrt2$ by graduate
students" remark is unpublished — do not cite it. Creation-time computation, run twice
independently: exhaustive over all $m!$ orderings, $f(K_3) = 2$, $f(K_4) = 2$,
$f(K_5) = 3$ and $\min\sum_v t(v) = 5, 8, 14$ (vs $|E| = 3, 6, 10$); branch-and-bound
(label 1 fixed by symmetry, prune once an increasing path of length 4 appears — valid
since adding edges only creates paths) shows no ordering of $K_6$ has longest increasing
path $\le 3$, and an explicit ordering attains $4$, so $f(K_6) = 4$; local search
$\min\sum_v t(v)$ for $K_6/K_7/K_8$ reached $20/28/36$ vs $|E| = 15/21/28$ (ratios
$1.33, 1.33, 1.29$, drifting toward $1$ — consistent with $K_n$ being asymptotically
extremal for the sum if $f(K_n) \sim n/2$); all 202 graphs on $\le 6$ vertices with an
edge (exhaustive for $m \le 10$, sampled for $m \ge 11$): $\min(\sum_v t(v) - |E|) = 1$,
attained only by $K_2$ — no violation.

**Known partial results (classified, with sources).**
- Trail version and Winkler's $\sum(\text{trail lengths}) = 2|E|$ (KNOWN_RESULT; note it
  does **not** prove the path statement).
- $n^{1-o(1)}$ lower / $(1/2+o(1))n$ upper for $f(K_n)$ (KNOWN_RESULTs; parsed sources
  for the lower bound; CCS journal-only).
- Random-ordering results (KNOWN_RESULTs; parsed sources) — about typical, not worst,
  orderings.
- Small exact values (creation-time computation — recompute here, do not cite).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/incpath.c (+ scripts/incpath.py driver) — (a) given a graph
   (graph6) and an ordering, compute $t(v)$ for all $v$ by DP over edges in increasing
   label order ($t$ = longest increasing path *starting* at $v$: process labels
   downward, $L(v, e)$ = longest path starting with edge $e$ at $v$); (b) exhaustive
   minimum of $\sum_v t(v)$ and of $\max_v t(v)$ over all $m!$ orderings for $m \le 10$,
   with symmetry reduction; branch-and-bound / CP-SAT for $K_6, K_7$; (c) simulated
   annealing over orderings for $K_7$–$K_{12}$ and for candidate extremal graphs;
   (d) verify any claimed ordering independently in Python.
2. exp_new(title="Increasing paths: exhaustive sum check, all graphs n <= 6",
   command="geng -q 6 | python scripts/incpath.py --exhaustive",
   environment="python-sci", run_from="workspace") then exp_run — reproduce
   $\min(\sum t - |E|) = 1$ only at $K_2$; then $K_6$ ($f = 4$, $\min\sum = 20$) exactly
   and heuristics for $K_7$–$K_{12}$.
3. Submit exact facts via proof_submit (sympy backend): the ordering of $K_5$ with
   $\sum_v t(v) = 14$ (explicit table, DP recomputed) and $f(K_5) = 3$; the
   one-line lemma $\sum_v t(v) \ge$ (number of vertices incident to the top edge) $\dots$
   whatever elementary bound is actually provable. Only ACCEPTED submissions are
   machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: one graph and one explicit ordering with
$\sum_v t(v) < |E|$ — an integer table, exactly re-checkable. Territory: dense graphs
(the sum bound is tight-ish only when many vertices have small $t$: $K_n$ ratios drift
toward $1$), complete bipartite and complete multipartite graphs, graphs of the
Calderbank–Chung–Sturtevant construction (their $K_n$ ordering with altitude $\sim n/2$
— what is $\sum_v t(v)$ for it?), and graphs where a small vertex set carries all high
labels. A verified counterexample claim must name the primary claim in depends_on.

**Proof track.** (i) Adapt Winkler's token argument: tokens on vertices moving along
edges in label order count trails; find a charging that counts paths (record exactly
where revisiting a vertex breaks it). (ii) Prove the sum conjecture for special classes
(trees, cycles, complete bipartite) as machine-checkable lemmas. (iii) Relate to the
altitude: the sum conjecture $\Rightarrow f(K_n) \ge (n-1)/2$; conversely, is
$\sum_v t(v) \ge |E|$ implied by a bound $t(v) \ge \deg(v)/2$ for *some* vertex ordering?
Every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exhaustive small-graph checks, exact $K_6$,
heuristic minima for $K_7$–$K_{12}$, evaluation of the CCS construction. Instances can
refute (one certified ordering suffices); they can never prove the all-graphs statement.

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
  --statement "For every finite graph G and every labelling of its edges by 1, 2, ..., |E(G)| in some order, the sum over all vertices v of the length t(v) of the longest increasing path starting at v is at least |E(G)|."
opentorus problem verdict "${TARGET}" --set-primary CLAIM-0001

# --- 7. Campaign run ---------------------------------------------------------
# (was: opentorus --verbose prove "${TARGET}" --min-papers 4)
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
