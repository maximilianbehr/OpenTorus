#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The distance antimagic conjecture
#                              (Kamatchi–Arumugam 2013)
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Graph theory: structural properties, labelings,
#         and connections to applications" (ed. A. Dawkins), Conjecture 1.45;
#         http://aimpl.org/graphstructureapp/1/ (http only). Origin: Kamatchi,
#         Arumugam, JCMCC 84 (2013) 61-67; independently Simanjuntak-Wijaya,
#         arXiv:1312.7405, Conjecture 3.1.
# Status audit 2026-08-17 (independently counter-checked): OPEN. Necessity of
# pairwise distinct open neighbourhoods is trivial; sufficiency is known only
# class by class (paths, cycles, wheels, hypercubes, complete graphs, several
# products, joins, coronas, circulants with one generator) and exhaustively
# for all graphs of order <= 8 (Simanjuntak et al. 2021), extended to order 9
# at creation (205914 distinct-neighbourhood graphs, all labelled; the order-8
# count 8047 was reproduced independently).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./distance_antimagic.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# graphs up to isomorphism; exact labelling search by backtracking / CP-SAT.
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
opentorus paper fetch https://arxiv.org/abs/1312.7405
opentorus paper fetch https://arxiv.org/abs/1309.7454
opentorus paper fetch https://arxiv.org/abs/2501.05035
opentorus paper fetch https://arxiv.org/abs/2501.05148

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The distance antimagic conjecture

**Primary target (general).** For every finite simple graph $G$ whose vertices have
pairwise distinct open neighbourhoods, $G$ is *distance antimagic*: there is a bijection
$f : V(G) \to \{1, \dots, |V(G)|\}$ such that the neighbourhood sums
$w(v) = \sum_{u \in N(v)} f(u)$ are pairwise distinct. (AIM graphstructureapp Conjecture
1.45, verbatim: "A graph is distance antimagic if and only if all the vertices have a
distinct neighborhood." The "only if" is trivial — equal open neighbourhoods force equal
sums under every labelling — so the content is sufficiency. Origin: Kamatchi–Arumugam,
J. Combin. Math. Combin. Comput. 84 (2013) 61–67; independently Simanjuntak–Wijaya,
[arXiv:1312.7405](https://arxiv.org/abs/1312.7405), Conjecture 3.1. Neighbourhoods are
*open*; the closed-neighbourhood variant is "inclusive distance antimagic", a different
conjecture. Disconnected graphs are allowed; at most one isolated vertex can occur, with
weight $0$.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open**.
No proof, counterexample, or claimed proof (arXiv sweep through Aug 2026 for "distance
antimagic" — the 2025–2026 hits are $D$-antimagic on oriented graphs, local and inclusive
variants). Everything known is class by class: paths ($n \ne 3$), cycles ($n \ne 4$),
wheels ($n \ne 4$), $rK_2 + K_1$ (Kamatchi–Arumugam 2013); cycles, suns, prisms, complete
graphs, wheels, fans, friendship graphs (Simanjuntak–Wijaya 2013; prisms' $(a,1)$-labelling
goes back to Arumugam–Kamatchi 2012); hypercubes $Q_n$, $n \ge 4$ (Kamatchi et al., LNCS
10398, 2017 — even $(a,d)$-distance antimagic); ladders, joins, coronas (Handa–Godinho–
Singh–Arumugam 2016/2017); $K_n \square K_n$ iff $n \ne 2$ (Cutinho–Sudha–Arumugam, AKCE
2020); sufficient conditions for $G + K_m$, $G \odot H$, $G \square K_2$, and
$K_n \odot K_m$ ($m$ odd), $K_n \square K_m$ for $(n,m) \ne (2,2)$ (Simanjuntak–Tritama,
Symmetry 2022; Wulandari–Simanjuntak, EJGTA 2023 — mind that their printed condition
"$m \ne 2$ and $n \ne 2$" is too strong: $K_3 \square K_2$ *is* distance antimagic, e.g.
with weights $8, \dots, 13$); $P_n \square K_2$, $C_n \square K_2$, $K_{n,n} \square K_2$
(Arumugam–Kamatchi 2012, Simanjuntak–Tritama); circulants with one generator characterised,
$C(n;\{1,k\})$ for $n$ odd (Sy–Simanjuntak–Nadeak–Sugeng–Tulus, AIMS Math. 2024);
vertex-deleted subgraphs, amalgamations, unions of paths (Wulandari–Simanjuntak–Saputro,
EJGTA 2025); shadow graphs (Ngurah–Inayah–Musti, EJGTA 2024); zero-divisor graphs
(arXiv:2407.08211). Group-labelled analogue for products: Cichacz–Froncek–Sugeng–Zhou
([arXiv:1309.7454](https://arxiv.org/abs/1309.7454)). State of the art surveyed in the
introductions of Abrar–Simanjuntak ([arXiv:2501.05035](https://arxiv.org/abs/2501.05035),
[arXiv:2501.05148](https://arxiv.org/abs/2501.05148)). Exhaustive verification: all
graphs of order $\le 8$ (Simanjuntak et al., Symmetry 13 (2021) 2071, via nauty).
Creation-time computation, run twice independently through order 8: the numbers of
graphs on $n = 1, \dots, 9$ vertices with pairwise distinct open neighbourhoods are
$1, 1, 2, 5, 16, 78, 588, 8047, 205914$, and **every one of them is distance antimagic**
(order 9 in about three minutes of exact backtracking — this extends the published
range by one); also all distinct-neighbourhood trees up to 18 vertices, 4692 random
graphs on 10–14 vertices, $Q_3$–$Q_5$, Petersen, $K_3 \square K_2$.

**Known partial results (classified, with sources).**
- Class-by-class theorems above (KNOWN_RESULTs; parsed sources for the arXiv ones,
  journal citations otherwise — cite, do not paraphrase beyond the audit).
- Necessity of distinct neighbourhoods (trivial lemma — prove it, do not cite it).
- Exhaustive order $\le 8$ (KNOWN_RESULT; Symmetry 2021) and order 9 (creation-time —
  recompute here, do not cite).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/dam.py — (a) read graph6 from stdin (geng), keep the graphs with
   pairwise distinct open neighbourhoods; (b) an exact labelling search: backtracking
   over vertex labels with forward checking on the partial sums (or a CP-SAT model:
   AllDifferent on labels, AllDifferent on weights); (c) output the labelling as a
   certificate and verify it in $O(m)$; report the number of graphs, failures, and the
   hardest instances.
2. exp_new(title="Distance antimagic: exhaustive n <= 8",
   command="geng -q 8 | python scripts/dam.py", environment="python-sci",
   run_from="workspace") then exp_run — reproduce 8047 graphs, zero failures; push to
   $n = 9$ (205914) and, as budget allows, targeted $n = 10$ families (regular graphs
   `geng -d3 -D3 10`, bipartite `genbg`, sparse graphs, graphs with many near-equal
   neighbourhoods).
3. Submit exact facts via proof_submit (sympy backend): explicit labellings for
   $Q_3$, Petersen, $K_3 \square K_2$, $C_5$ (checked sums), and the necessity lemma.
   Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: one graph with pairwise distinct open neighbourhoods and
no distance antimagic labelling — a finite object whose certificate is an exhaustive
UNSAT proof over the $n!$ bijections (symmetry-reduced; DRAT/CP log). Territory:
$n \ge 10$; graphs whose neighbourhoods differ minimally (twins-plus-one-vertex
constructions, "near-twin" pairs $N(u) \triangle N(v) = \{x\}$ for many pairs);
regular graphs where all weights must fit in a narrow window; disconnected graphs with a
small component; graphs where the multiset of degrees forces weight collisions by a
counting argument. A verified counterexample claim must name the primary claim in
depends_on.

**Proof track.** Look for a mechanism: (i) a probabilistic argument — a random
bijection gives distinct weights unless many pairs have small $N(u) \triangle N(v)$;
quantify with a Lovász-local-lemma or Combinatorial-Nullstellensatz approach on the
weight polynomial $\prod_{u < v}(w(u) - w(v))$; (ii) reduce to the case
$|N(u) \triangle N(v)| = 1$ pairs and handle them by a switching argument; (iii)
inductive constructions (vertex addition, joins, products) that cover new classes.
Every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exhaustive certificates for
$n \le 9$, targeted families at $n = 10$–$12$, statistics of the search hardness versus
the "near-twin" structure. Instances can refute (one certified UNSAT graph suffices);
they can never prove the all-graphs statement.

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
  --statement "For every finite simple graph G in which all vertices have pairwise distinct open neighbourhoods, G is distance antimagic: there is a bijection f from V(G) to {1,...,|V(G)|} such that the neighbourhood sums w(v) = sum of f(u) over u adjacent to v are pairwise distinct."
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
