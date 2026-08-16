#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — Sidorenko's conjecture
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-14, amended 2026-08-15 after peer cross-check: OPEN in
# general. Known for trees, even cycles, complete bipartite graphs, bipartite
# graphs with a vertex complete to the other side, suitable blow-ups (for every
# bipartite H some blow-up H^p is Sidorenko; arXiv:1809.01259),
# subdivisions/theta substitutions (arXiv:2408.03491), and broad recursive
# families (Conlon-Kim-Lee-Lee line); an approximate version holds
# (Conlon-Fox-Sudakov). Simplest unknown case: K_{5,5} minus a 10-cycle
# (isomorphic to the Moebius ladder on 10 vertices).
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./sidorenko.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Exact homomorphism counting (small H, weighted G), gradient searches over
# edge-weighted graphons discretized as matrices, networkx for graph handling.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy networkx
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/1809.01259
opentorus paper add https://arxiv.org/abs/2408.03491

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Sidorenko's conjecture

**Primary target (general).** For every bipartite graph $H$ and every graph $G$, the
homomorphism density satisfies $t_H(G) \ge t_{K_2}(G)^{e(H)}$ — i.e. among graphs of a
given edge density, quasirandom graphs asymptotically minimize the number of copies of
every bipartite $H$.

**Status audit (2026-08-14; amended 2026-08-15 after an independent cross-check).**
Fresh web check: **open in general**, with a
large and growing family of settled cases. Known Sidorenko classes include trees, even
cycles, complete bipartite graphs, bipartite graphs with a vertex adjacent to the entire
other side, suitable blow-ups (for every bipartite $H$ some blow-up $H^p$ is Sidorenko,
plus a divisibility-condition class — Conlon–Lee,
[arXiv:1809.01259](https://arxiv.org/abs/1809.01259)),
subdivisions and theta substitutions
([arXiv:2408.03491](https://arxiv.org/abs/2408.03491)), and recursively built families
(Conlon–Kim–Lee–Lee line). An approximate version holds for
all bipartite $H$ (Conlon–Fox–Sudakov). The simplest case still unknown is
$K_{5,5}$ minus a 10-cycle (isomorphic to the Möbius ladder on 10 vertices). No
refutation is known; the conjecture is equivalent to a
statement about graphons, so a counterexample may be an edge-weighted graph.

**Known partial results (classified, with sources).**
- Trees, even cycles, complete bipartite graphs — Sidorenko's original classes
  (KNOWN_RESULT; cite parsed sources).
- Blow-ups: for every bipartite $H$ there is a $p \ge 1$ with $H^p$ Sidorenko, plus a
  divisibility-condition class — Conlon–Lee, arXiv:1809.01259 (NOT "all blow-ups of
  Sidorenko graphs").
- Subdivisions / theta substitutions — arXiv:2408.03491.
- Approximate Sidorenko for all bipartite $H$ — Conlon–Fox–Sudakov (KNOWN_RESULT).
- $K_{5,5}\setminus C_{10}$ open — the canonical frontier instance (a TOOL here, not the
  target).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/hom_density.py — EXACT homomorphism density $t_H(G)$ for a small
   bipartite $H$ against a rational edge-weighted $G$ (sympy Rationals, no floats),
   plus the deficit $t_H(G) - p^{e(H)}$.
2. exp_new(title="Sidorenko deficit landscape",
   command="python scripts/hom_density.py", environment="python-sci",
   run_from="workspace") then exp_run — deficits for $H \in \{P_3, C_4, C_6,
   K_{3,3}\}$ against structured and randomly perturbed weighted $G$ (numeric search
   allowed, but every reported value must be recomputed exactly).
3. Submit each exact instance inequality as a certificate via proof_submit (sympy
   backend): "for this H and this rational G, t_H(G) - p^{e(H)} equals exactly d >= 0".
   Only ACCEPTED submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a bipartite $H$ and a (possibly
edge-weighted) $G$ with $t_H(G) < t_{K_2}(G)^{e(H)}$. Generators: $H$ near the known
frontier ($K_{5,5}\setminus C_{10}$, Möbius-ladder-like structures, sparse
vertex-transitive bipartite graphs outside the settled classes); $G$ as small weighted
matrices optimized by projected gradient / annealing on $t_H(G) - p^{e(H)}$. Any
numerical candidate must be completed to an exact witness: rational edge weights, exact
homomorphism count via sympy (the density inequality for fixed $H$, fixed rational $G$
is a finite computation), certified via proof_submit. A verified counterexample claim
must name the primary claim in depends_on.

**Proof track.** Reproduce the settled-class inequalities on generated instances;
entropy / dependent-random-choice lemma candidates tested against the instance zoo;
attack the frontier instance as a LEMMA (settling $K_{5,5}\setminus C_{10}$ either way
feeds the general question without being it); track which structural features
(degeneracy, tree-decomposability, norming) separate settled from open classes; every
unresolved inference an explicit [GAP-n].

**Instance program (tools, not targets).** Exact $t_H(G)$ computation for small $H$
against structured and optimized weighted $G$; minimizer-landscape statistics (are
near-minimizers quasirandom?); the $K_{5,5}\setminus C_{10}$ deficit landscape in
particular. Instances can refute (one exact witness suffices); they can never prove the
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
  --statement "For every bipartite graph H and every graph G, the homomorphism density satisfies t_H(G) >= t_{K2}(G)^{e(H)}."
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
