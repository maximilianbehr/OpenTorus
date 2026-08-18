#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Alon–Boppana for the non-backtracking notion of
#                              Ramanujan graphs (irregular graphs)
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Source: AIM Problem List "Connecting communities via the block model"
#         (ed. A. Wein; AIM workshop May 22-26, 2017), Section 5 "Random
#         matrix theory", Problem 5.4 [Laurent Massoulie], with 5.1 (power-law
#         Chung-Lu graphs) and 5.5 (constructions) as tools;
#         http://aimpl.org/blockmodel/5/ (http only). The same lower-bound
#         question is Problem 1.3(2) of the AIM list "Spectral graph and
#         hypergraph theory" (Dec 2021), http://aimpl.org/spectralhypergraph/1/ .
# Status audit 2026-08-17 (independently counter-checked): OPEN as posed for
# the connected, exactly-fixed-rho version - and FALSE for two literal
# readings, exhibited and certified at creation: (i) the leafless-only form
# of spectralhypergraph 1.3(2) and (ii) any "rho_n -> rho" reading fail for
# an explicit family (an 8-vertex minimiser with a long cycle attached keeps
# |lambda_2(B)|/sqrt(rho) = 0.94705 while n -> infinity and rho_n -> rho
# exponentially fast; exhaustive over all 8025 connected graphs with min
# degree >= 2 on <= 8 vertices, 131 of them below ratio 1); disconnected
# graphs reach exact rho trivially. Regular graphs: exact and trivial via
# Ihara-Bass (NB-Ramanujan <=> Ramanujan). Upper side known: sparse ER (BLM
# arXiv:1501.06087) and random n-lifts (Bordenave arXiv:1502.04482) are
# NB-Ramanujan whp; the universal cover has NB spectral radius exactly
# sqrt(rho) (Angel-Friedman-Hoory arXiv:0712.0192). No proof of the lower
# bound in any form was found.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL; the campaign budget with
# OPENTORUS_BRANCHES / OPENTORUS_MAX_STEPS / OPENTORUS_MAX_WALL_SECONDS).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./nonbacktracking_ramanujan.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# nauty geng (Debian package; symlinked) for exhaustive graph generation,
# numpy/scipy for non-backtracking spectra (Ihara-Bass 2n x 2n reduction),
# sympy for exact integer characteristic polynomials and root isolation.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nauty \
 && rm -rf /var/lib/apt/lists/* \
 && for f in /usr/bin/nauty-*; do ln -sf "$f" "/usr/bin/${f#/usr/bin/nauty-}"; done
RUN pip install --no-cache-dir numpy scipy sympy networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/1501.06087
opentorus paper add https://arxiv.org/abs/0712.0192
opentorus paper add https://arxiv.org/abs/1502.04482
opentorus paper add https://arxiv.org/abs/2011.09385

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Alon–Boppana for the non-backtracking notion of Ramanujan graphs

**Primary target (general).** For a finite graph $G$ let $B$ be its non-backtracking
matrix on directed edges ($B_{(u\to v),(x\to y)} = 1$ iff $v = x$ and $u \ne y$), with
eigenvalues ordered by modulus and Perron eigenvalue $\rho = |\lambda_1(B)|$ (the growth
rate of the universal cover). Bordenave–Lelarge–Massoulié call $G$ *NB-Ramanujan* if
$\mathrm{Sp}(B) \subseteq \{\rho e^{i\theta}\} \cup \mathcal B(0, \sqrt\rho)$ — the graph
Riemann hypothesis of Stark–Terras. **Conjecture (Alon–Boppana analogue; AIM blockmodel
5.4, L. Massoulié):** for every fixed $\rho > 1$, every connected graph $G_n$ with
minimum degree $\ge 2$, $|\lambda_1(B_{G_n})| = \rho$ exactly, and $n \to \infty$ satisfies
$|\lambda_2(B_{G_n})| \ge \sqrt\rho - o(1)$. (The primary claim is stated for CONNECTED
graphs with $\rho$ EXACTLY fixed — the version that survives the certified
counterexamples below.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: **open as
posed for the connected exact-$\rho$ version; false for two literal readings.** No proof,
refutation, or claim of the lower bound was found in any form. What is exact: for
$d$-regular graphs Ihara–Bass pairs the nontrivial NB eigenvalues with product $d-1$, so
$|\lambda_2(B)| \ge \sqrt{d-1} = \sqrt\rho$ trivially and NB-Ramanujan ⟺ Ramanujan; every
non-real NB eigenvalue has $\sqrt{\delta-1} \le |\mu| \le \sqrt{\Delta-1}$ (Kotani–Sunada
2000), and $|\mu| \ge 1$ when $\delta \ge 2$ (Glover–Kempton,
[arXiv:2011.09385](https://arxiv.org/abs/2011.09385)). Upper side: sparse
Erdős–Rényi $G(n,\alpha/n)$ has $\rho = \alpha + o(1)$ and $|\lambda_2| \le \sqrt\alpha + o(1)$
whp (BLM, [arXiv:1501.06087](https://arxiv.org/abs/1501.06087)); new NB eigenvalues of
random $n$-lifts are $\le \sqrt{\rho} + o(1)$ (Bordenave,
[arXiv:1502.04482](https://arxiv.org/abs/1502.04482), Thm 23); the NB spectral radius of
the universal cover is exactly $\sqrt\rho$ (Angel–Friedman–Hoory,
[arXiv:0712.0192](https://arxiv.org/abs/0712.0192)) — the heuristic reason $\sqrt\rho$ is
the right threshold. Creation-time computation (independently re-run; recompute, do not
cite): over all 8025 connected graphs with $\delta \ge 2$ on $\le 8$ vertices (counts
1, 3, 11, 61, 507, 7442 = OEIS A004108), $\min |\lambda_2|/\sqrt\rho = 1$ for $n \le 5$,
$0.99158$ ($n = 6$), $0.95598$ ($n = 7$), $0.94705$ ($n = 8$; 131 graphs below 1); the
$n = 8$ minimiser has edges $\{01, 07, 12, 15, 17, 23, 26, 34, 47, 56, 57, 67\}$,
$\rho = 2.18424$, $|\lambda_2| = 1.39966$ (roots of an explicit integer polynomial —
exact certificate). Attaching a cycle $C_N$ at a vertex gives connected $\delta \ge 2$
graphs with $n \to \infty$, $\rho_N \to \rho$ exponentially fast (not exactly equal) and
ratio $0.94705$ for all large $N$ — so (i) the leafless-only wording of spectralhypergraph
1.3(2), which has no "$\rho$ fixed" clause, is FALSE as written, and (ii) any
"$\rho_n \to \rho$" reading of 5.4 is false; disconnected graphs (minimiser $\sqcup$ $k$
triangles) even reach exact $\rho$ trivially. With $\delta \ge 3$ the cheapest such gadget
has ratio $0.9852$, and a cubic tail restores $|\lambda_2| \to 2 > \sqrt\rho$; random
$k$-lifts of the minimiser ($k \le 40$) always had new eigenvalues above $\sqrt\rho$.
Tools from the same AIM section: 5.1 (are power-law Chung–Lu graphs NB-Ramanujan with
radius $\sqrt{\tilde d}$, $\tilde d = \sum d_v^2/\sum d_v - 1$? — open; Stephan–Massoulié
arXiv:2004.07408 need delocalized eigenvectors, excluding heavy tails) and 5.5
(constructions of irregular NB-Ramanujan graphs — Terras et al. remark they are rare).

**Known partial results (classified, with sources).**
- Regular case exact; Kotani–Sunada / Glover–Kempton modulus bounds (KNOWN_RESULTs).
- Upper-side theorems: BLM sparse ER, Bordenave lifts, AFH universal cover (KNOWN_RESULTs;
  they prove the UPPER bound $\le \sqrt\rho + o(1)$, never the lower bound).
- The certified small-graph minimisers and the cycle-attachment family (creation-time
  computation — reproduce and certify; they refute the two literal readings and are
  VERIFIED_COUNTEREXAMPLE_TO_AUXILIARY_CLAIM material, not a refutation of the primary
  claim).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/nb_spectrum.py — (a) the non-backtracking matrix and its spectrum,
   via the Ihara–Bass $2n \times 2n$ reduction for speed; (b) $\rho$, $|\lambda_2|$, the
   ratio, and an exact certificate for a flagged graph (integer characteristic polynomial
   of $B$, sympy real/complex root isolation); (c) a graph6 stdin pipeline for geng; (d)
   the cycle-attachment and disjoint-union gadgets and random $k$-lifts.
2. exp_new(title="NB Alon-Boppana: exhaustive small graphs and gadget families",
   command="geng -c -d2 8 -q | python scripts/nb_spectrum.py", environment="python-sci",
   run_from="workspace") then exp_run — reproduce the ratio minima for $n \le 8$ (exact
   counts), the $n = 8$ minimiser certificate, and the cycle-attachment family for
   $N = 10, 20, 40, 80$ (ratio and $\rho_N - \rho$); push to $n = 9$ if budget allows;
   record the $\delta \ge 3$ minimum.
3. Submit exact facts via proof_submit (sympy backend): "the graph with edges {…} has
   $\rho$ and $|\lambda_2|$ as isolated real algebraic numbers with $|\lambda_2| < \sqrt\rho$"
   (certified counterexample to the leafless-only wording); exhaustive per-$n$ minima.
   Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track (of the connected exact-$\rho$ claim).** Negate: a connected family
with $\delta \ge 2$, $|\lambda_1(B)| = \rho$ EXACTLY for all $n$, and $|\lambda_2| \le
\sqrt\rho - c$. Exact $\rho$ along a family is the whole difficulty: covers ($k$-lifts)
preserve $\rho$ exactly but experiments show their new eigenvalues exceed $\sqrt\rho$ —
test more lifts (abelian, random, structured) of the small minimisers, and search for
other exact-$\rho$-preserving operations (e.g. attaching structures whose universal cover
matches). Every candidate exactly certified; a verified counterexample claim must name
the primary claim in depends_on.

**Proof track.** Reproduce the AFH universal-cover argument on the parsed paper (why
$\sqrt\rho$ is unavoidable for the cover) and identify what a finite-graph lower bound
needs (a moment/trace method à la Alon–Boppana adapted to irregular NB walks — Banks–
Trevisan's vector-chromatic bound and Abbe–Ralli's powered-graph Alon–Boppana are the
nearest technology); test candidate hypotheses ("locally uniform families", "common
universal cover") on the zoo; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** Exhaustive small-graph minima with certificates,
gadget families refuting the literal readings, lift experiments, power-law Chung–Lu
NB spectra (5.1) and small NB-Ramanujan irregular graphs (5.5) as side tables. Instances
can refute (an exact-$\rho$ connected family with proof); they can never prove the
asymptotic statement.

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
  --statement "For every fixed rho > 1, every sequence of connected graphs with minimum degree at least 2 whose non-backtracking matrices have Perron eigenvalue exactly rho satisfies |lambda_2(B)| >= sqrt(rho) - o(1) as the number of vertices tends to infinity."
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
