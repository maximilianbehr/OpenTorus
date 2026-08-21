#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — Positive and negative square energies of
#                                 graphs (a four-week-old claimed proof plus
#                                 refuted auxiliary conjectures)
#
# KNOWN ground truth (see README.md), from AIM Problem List "Spectral graph
# and hypergraph theory: connections and applications" (ed. S. Mohanty, AIM
# workshop Dec 6-10 2021), Problem 1.4, http://aimpl.org/spectralhypergraph/1/
# (http only). Part (1), the Elphick-Farber-Goldberg-Wocjan conjecture
# min{S+, S-} >= n-1 for every connected graph, was CLAIMED PROVED on
# 2026-07-20 (Liu-Tang-Zhang, arXiv:2607.18031, unrefereed, four weeks old at
# audit; the audit's first pass had it as "open, best bound 3n/4" - the
# counter-audit caught the preprint). Parts (2)-(4), the workshop's edge-
# addition monotonicity questions, are REFUTED with exact small certificates
# (Godsil's 9-vertex S+ decrease in Abiad et al., ELA 2023, arXiv:2303.11930;
# an infinite family in Tang-Liu-Wang, DAM 2026, arXiv:2410.09830; a 5-vertex
# S- non-unimodality found and independently re-run at creation). This run
# tests two labels at once: "claimed / under review" for (1) and
# "refuted, with reproduced exact counterexamples" for (2)-(4).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./square_energy.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
opentorus config set model.timeout_seconds 1200
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set agent.prove_gap_fill_max_steps inf
opentorus config set permissions.mode trusted

# --- 3. Numerical experiment environment ------------------------------------
# nauty geng (Debian package; nauty-prefixed binaries symlinked) for
# exhaustive small graphs, numpy spectra, sympy exact root isolation.
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
opentorus paper add https://arxiv.org/abs/2607.18031
opentorus paper add https://arxiv.org/abs/1409.2079
opentorus paper add https://arxiv.org/abs/2303.11930
opentorus paper add https://arxiv.org/abs/2410.09830
opentorus paper add https://arxiv.org/abs/2409.18220

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Positive and negative square energies of graphs — determine the status of the AIM questions

**Setup.** For a connected graph $G$ on $n$ vertices with adjacency eigenvalues
$\lambda_1 \ge \dots \ge \lambda_s \ge 0 > \lambda_{s+1} \ge \dots \ge \lambda_n$, let
$S^+(G) = \sum_{i \le s}\lambda_i^2$ and $S^-(G) = \sum_{i > s}\lambda_i^2$ ($S^+ + S^- = 2m$).
AIM spectralhypergraph Problem 1.4 asks: (1) prove $\min\{S^+, S^-\} \ge n-1$
(Elphick–Farber–Goldberg–Wocjan 2016); (2) prove that along any edge-addition chain
$G = G_0 \subset G_1 \subset \dots \subset K_n$ the sequence $S^+(G_i)$ increases and
$S^-(G_i)$ is unimodal; (3) is $\sum_{t \le r}\lambda_t(G_i)^2$ monotone? (4) is
$\sum_{\lambda_t \ge \tau}\lambda_t(G_i)^2$ monotone?

**Task for this dossier.** Determine the *current* status of each part and produce an
honest status sketch with the right label on each:

1. **Part (1) — claimed / under review.** A July 2026 preprint (Liu–Tang–Zhang,
   arXiv:2607.18031, 12 pages) claims a full proof of $\min\{S^+,S^-\} \ge n-1$ for every
   connected graph (via a relaxation of the Hadamard squares $A^\pm \circ A^\pm$ to the
   doubly nonnegative cone), together with EFGW's second conjecture ($n - \kappa$ for
   $\kappa$ components) and related $p$-energy conjectures. Report it as claimed and
   unrefereed (four weeks old at audit time), never as an established theorem, and never
   omit it by calling the conjecture simply "open". The established layer before it:
   $\min\{S^+,S^-\} \ge 3n/4$ for $n \ge 4$ (Akbari–Kumar–Mohar–Pragada, arXiv:2409.18220,
   EJC 2025), $\ge n - \gamma$ (Zhang), many settled classes (bipartite, regular, complete
   multipartite, hyperenergetic, cycles, threshold, dominating vertex, $\gamma \le 2$,
   maximal planar, claw-free with $\Delta \ge 3$ …), exhaustive verification for all
   connected graphs to $n = 10$; unicyclic graphs were the believed bottleneck
   (Ning–Zeng, arXiv:2605.24668, settle only a mod-4 comparison there).
2. **Parts (2)–(4) — refuted, and the refutations are to be REPRODUCED exactly.**
   $S^+$ can decrease when an edge is added: Godsil's five 9-vertex graphs (Abiad–de
   Lima–Desai–Guo–Hogben–Madrid, arXiv:2303.11930, ELA 39 (2023), Ex. 2.6 — present in
   the ELA version, not the arXiv v1): the complement of the double star $S_{5,4}$ has
   $S^+ = 44.84759\ldots$ and adding the centre edge gives $44.84247\ldots$; an infinite
   family (complements of $S_{n,n}$) and failure for all $p$-energies with $1 \le p < 3$
   (Tang–Liu–Wang, arXiv:2410.09830, DAM 2026; $p \ge 3$ open). $S^-$ unimodality fails
   from the 5-vertex tree with edges $\{24, 12, 23, 01\}$ adding $02, 03, 13, 34, 14, 04$:
   $S^- = 4, 4.289, 4.676, 4.293, 4.827, 4.708, 4$ (found at creation, independently
   re-run). (3) fails for $r \ge 2$ and (4) for generic $\tau$ already at $n = 7$; what
   survives is $S^+(G) \ge S^+(G-e) - \theta_2^2$ (Abiad et al.). Verify each
   counterexample with exact algebraic eigenvalues (sympy real root isolation) and record
   them through the proper pathway (COUNTEREXAMPLE_VERIFIED for the auxiliary claims —
   these do NOT touch part (1)).
3. **Numerics (support for (1); theorems for the instances checked).** Stream all
   connected graphs on $\le 8$ vertices through geng, verify (1) with exact certificates
   near equality (trees: $S^+ = S^- = n-1$; $K_n$: $S^- = n-1$), and record how (1)'s
   claimed proof would be tested (e.g. does the DNN relaxation bound hold with equality
   exactly where the certificates say?).

**Honesty requirements.** "Claimed" and "proved" stay distinct; the refutations of
(2)–(4) are reported as refutations only with the certificates reproduced in this
workspace; the pre-2026 partial results are cited from parsed PAPER-* artifacts; the
claw-free statement needs $\Delta \ge 3$ (paths have $S^+ = n-1$).
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Survey + certified numerics ------------------------------------------
# `prove` gates on the honesty linter: a report that still overclaims exits non-zero.
# That is a finding to read, not a crash — but under `set -e` it aborted this driver
# right here, before the report/verdict/PDF steps below ever ran. Keep the signal,
# finish the workflow, and exit with it at the end.
PROVE_RC=0
opentorus --verbose prove "${TARGET}" --min-papers 4 || PROVE_RC=$?

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: part (1) labelled claimed/under review (arXiv:2607.18031, Jul 2026)"
echo "with the pre-2026 3n/4 theorem layer kept separate; parts (2)-(4) labelled refuted with"
echo "the Godsil S+ decrease and the 5-vertex S- non-unimodality reproduced EXACTLY and"
echo "recorded as verified counterexamples to the auxiliary claims."

exit "${PROVE_RC}"
