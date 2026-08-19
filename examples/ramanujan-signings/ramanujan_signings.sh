#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Random signings of Ramanujan graphs
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Connecting communities via the block model"
#         (ed. A. Wein; AIM workshop May 22-26, 2017), Section 5 "Random
#         matrix theory", Problem 5.3 [Nikhil Srivastava];
#         http://aimpl.org/blockmodel/5/  (site serves http only).
# Status audit 2026-08-17 (independently counter-checked): PARTIALLY
# RESOLVED, open in general. Mohanty-O'Donnell-Paredes (STOC 2020,
# arXiv:1909.06988) prove that a uniformly random signing of any d-regular
# graph that is bicycle-free at radius r >> (log log n)^2 has spectral radius
# <= 2 sqrt(d-1)(1+o(1)) whp - a YES for large-girth Ramanujan families
# (LPS, Morgenstern) and random regular graphs. OPEN: Ramanujan bases with
# many short cycles (bicycle-free radius o((log log n)^2)). Background: Bilu-
# Linial (random signing of small-set expanders, O(sqrt(d log^3 d))), Marcus-
# Spielman-Srivastava (a one-sided good signing exists), Agarwal-Chandrasekaran-
# Kolla-Madan (lambda + O(sqrt d) whp). A June-2026 deterministic-signing
# preprint (arXiv:2606.28797) was WITHDRAWN 2026-07-09.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_BRANCH_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./ramanujan_signings.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Spectra of signed adjacency matrices (numpy), exact eigenvalue certificates
# (sympy), named Ramanujan graphs and LPS constructions (networkx + own code).
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
# `paper fetch` downloads and parses the (audit-verified) arXiv sources so the
# campaign's literature branch has local text from its first visit; a failed
# download degrades to a metadata-only registration (never a hard stop).
opentorus paper fetch https://arxiv.org/abs/1909.06988
opentorus paper fetch https://arxiv.org/abs/math/0312022
opentorus paper fetch https://arxiv.org/abs/1304.4132
opentorus paper fetch https://arxiv.org/abs/1311.3268

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Random signings of Ramanujan graphs (2-lifts)

**Primary target (general).** For every fixed $d \ge 3$ and every $\varepsilon > 0$: for
every $d$-regular Ramanujan graph $G$ (all adjacency eigenvalues other than $\pm d$ have
modulus $\le 2\sqrt{d-1}$) with adjacency matrix $A$, let $S$ be the random signed
adjacency matrix ($S_{ij} = 0$ if $A_{ij} = 0$, independent uniform $\pm 1$ on each edge,
symmetric). Then $\lVert S\rVert < 2\sqrt{d-1} + \varepsilon$ with probability bounded
below by a constant $c(d, \varepsilon) > 0$ independent of $n$. (AIM Problem List
"Connecting communities via the block model", Problem 5.3, N. Srivastava. Since the
spectrum of the 2-lift $G_\sigma$ is $\mathrm{Spec}(A) \sqcup \mathrm{Spec}(S_\sigma)$,
this asks whether a random 2-lift of a Ramanujan graph is nearly Ramanujan with constant
probability.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **partially
resolved, open in general.** Mohanty–O'Donnell–Paredes
([arXiv:1909.06988](https://arxiv.org/abs/1909.06988), STOC 2020; Thm 1.2, refined Thm
3.1): for any $d$-regular $n$-vertex $G$ ($d \le \mathrm{polylog}\, n$) that is
*bicycle-free at radius* $r \gg (\log\log n)^2$ (every $r$-ball contains at most one
cycle), a uniformly random signing has $\rho(S) \le 2\sqrt{d-1}\,(1 + O((\log\log n)^4/r^2))$
except with probability $n^{-100}$ — a YES (with $o(1)$ in place of $\varepsilon$, whp) for
large-girth Ramanujan families (LPS, Morgenstern; girth $\Omega(\log n)$) and for random
regular graphs (Ramanujan with probability $\approx 69\%$, Huang–McKenzie–Yau
arXiv:2412.20263). What remains open is exactly the complementary case: Ramanujan graphs
with many short cycles (bicycle-free radius $o((\log\log n)^2)$). Background layer:
Bilu–Linial ([arXiv:math/0312022](https://arxiv.org/abs/math/0312022)): a random signing
of a good small-set expander has $\rho(S) = O(\sqrt{d\log^3 d})$ whp, and the
Bilu–Linial conjecture (a signing with $\rho(S) \le 2\sqrt{d-1}$ always exists) — the
best two-sided existence bound is NOT this one: the withdrawal note of a June-2026
interlacing-families preprint claiming $2\sqrt{3(d-1)}$ (arXiv:2606.28797, withdrawn
2026-07-09) says stronger results already exist — locate them in the parsed literature
before citing any "best known" two-sided bound;
Marcus–Spielman–Srivastava ([arXiv:1304.4132](https://arxiv.org/abs/1304.4132)): some
signing has $\lambda_{\max}(S) \le 2\sqrt{d-1}$ (existence, one-sided); Agarwal–
Chandrasekaran–Kolla–Madan ([arXiv:1311.3268](https://arxiv.org/abs/1311.3268)): for any
$d$-regular $G$ with $\lambda(G) \le \lambda$, a random $\mathbb{Z}_k$-lift's new
eigenvalues are $\le \lambda + O(\sqrt d)$ with probability $1 - k e^{-\Omega(n/d^2)}$
($k = 2$ is exactly $S$); Bandeira–van Handel (arXiv:1408.6185): $\mathbb E\lVert S\rVert \le (1+\varepsilon)2\sqrt d
+ C(\varepsilon)\sqrt{\log n}$ for ANY $d$-regular $G$ (sharp only for $d \gg \log n$,
with $2\sqrt d$ rather than $2\sqrt{d-1}$). A different regime —
$n$-lifts of a fixed base as $n \to \infty$ — is settled (Friedman–Kohler, Bordenave,
Bordenave–Collins). (MOP's Thm 1.2 is stated as $2\sqrt{d-1} + o_n(1)$ whp; the $n^{-100}$ failure
probability is its Thm 3.1.) A related 2026 route to fixed-base random lifts is the
strong-convergence proof of Chen–Garza-Vargas–Tropp–van Handel (arXiv:2405.16026,
Ann. Math. 2026). Wang–Lau–Zhou
(arXiv:2601.08111, 2026) derandomize signings for $d \gtrsim \log^4 n$.

**Known partial results (classified, with sources).**
- MOP bicycle-free theorem (KNOWN_RESULT; the hypothesis must be stated every time).
- Bilu–Linial random-signing bound and conjecture; MSS one-sided existence; ACKM
  $\lambda + O(\sqrt d)$; Bandeira–van Handel large-$d$ (KNOWN_RESULTs; parsed sources).
- Small named graphs computed exactly at creation (audit computation, exhaustive over
  all signings): $\mathbb P(\lVert S\rVert \le 2\sqrt{d-1})$ = $K_4$: .75, $K_{3,3}$: .94,
  Petersen: .97, Heawood: .91, Dodecahedron: .85, Desargues: .96, Coxeter: .91,
  Tutte–Coxeter: .95, $K_5$: .97, Octahedron: .80, $K_{4,4}$: .97, $K_6$: .85, $K_7$: .89
  (independently re-run at creation); with $\varepsilon = 0.25$ most rise to $\ge .98$
  but the complete graphs do not ($K_5$: .969, $K_6$: .969, $K_7$: .979 — their bad
  switching classes sit at $\rho = 4$) — recompute, do not cite from memory.
- Elementary observation to test: $\rho(S|_H) \le \lambda_1(H) \le \lambda_2(G) + d|H|/n$
  for an induced subgraph $H$, so bounded-size local obstructions cannot break the
  conjecture for Ramanujan bases (state as a LEMMA candidate; prove or mark [GAP]).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/signings.py — (a) exact enumeration of all signings of a small
   graph modulo switching equivalence ($2^{m-n+1}$ classes; uniform over classes =
   uniform over signings) with $\lVert S\rVert$ by numpy eigvalsh, (b) Monte Carlo
   $\lVert S\rVert$ for larger graphs, (c) constructors: named Ramanujan graphs (Petersen,
   Heawood, Coxeter, Tutte–Coxeter, Hoffman–Singleton, Paley graphs), LPS graphs
   $X^{p,q}$ for small $p, q$, and short-cycle-rich Ramanujan graphs (complete graphs,
   $K_{d,d}$, small Cayley graphs), and (d) an exact certificate routine: for a fixed
   integer $S$, isolate the extreme eigenvalue (sympy characteristic polynomial, real
   root isolation) and compare with $2\sqrt{d-1}$ exactly.
2. exp_new(title="Random signings: exact small graphs and Monte Carlo families",
   command="python scripts/signings.py", environment="python-sci",
   run_from="workspace") then exp_run — reproduce the exact table above; then Monte
   Carlo (thousands of signings) on LPS graphs vs short-cycle Ramanujan graphs of
   comparable degree, recording $\mathbb P(\lVert S\rVert \le 2\sqrt{d-1} + \varepsilon)$
   for $\varepsilon \in \{0, 0.1, 0.25\}$ and the excess distribution.
3. Submit exact facts via proof_submit (sympy backend): "for the Petersen graph, exactly
   N of the 2^{m-n+1} switching classes have $\lVert S\rVert \le 2\sqrt2$" (each class
   certified by exact root isolation). Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a family of $d$-regular Ramanujan graphs $G_n$ with
$\mathbb P(\lVert S\rVert < 2\sqrt{d-1} + \varepsilon) \to 0$. By MOP such a family must
have bicycle-free radius $o((\log\log n)^2)$ — dense short cycles. Search: Ramanujan
graphs assembled from many small dense gadgets (Cayley graphs of small groups, products,
covers with short cycles) while keeping the Ramanujan property (check exactly); track how
$\mathbb P(\lVert S\rVert \le 2\sqrt{d-1}+\varepsilon)$ scales with $n$ within a family. A
family with a proof would refute; a single graph never does. Every reported probability
for small graphs is exact; a verified counterexample claim must name the primary claim in
depends_on.

**Proof track.** Reproduce the MOP structure (bicycle-free radius ⇒ trace-method bound)
on the parsed paper and identify precisely where short cycles break it; test the local
obstruction lemma above; test whether the constant-probability version follows from
weaker hypotheses (e.g. bounded number of short cycles per vertex) on the instance zoo;
every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exact signing statistics for small
Ramanujan graphs, Monte Carlo on LPS and short-cycle families, excess-over-threshold
distributions vs. cycle statistics. Instances certify single graphs; they can never
prove or refute the all-$n$ statement.

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
  --statement "For every fixed d >= 3 and every epsilon > 0 there is a constant c > 0 such that for every d-regular Ramanujan graph G, a uniformly random signing S of the adjacency matrix of G satisfies ||S|| < 2 sqrt(d-1) + epsilon with probability at least c."
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
