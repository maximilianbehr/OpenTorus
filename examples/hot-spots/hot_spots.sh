#!/usr/bin/env bash
# ============================================================================
# OpenTorus CAMPAIGN example — The hot spots conjecture (planar convex case)
# Template: examples/CAMPAIGN_TEMPLATE.md (general-conjecture scope policy).
# Status audit 2026-08-17 (independently counter-checked): the PLANAR convex
# case is OPEN; the high-dimensional convex case was REFUTED in a Dec 2024
# preprint (de Dios Pont, arXiv:2412.06344: smooth centrally symmetric convex
# bodies in R^d, d large, with interior-only maximum - still unpublished).
# Settled planar classes: all triangles (Judge-Mondal, Annals 2020 + erratum
# 2022; sharpened by Chen-Gui-Yao, Invent. math. 244 (2026)), lip domains
# (Atar-Burdzy 2004), convex domains with two symmetry axes
# (Jerison-Nadirashvili 2000), kites/parallelograms/trapezoids under
# hypotheses (arXiv:2604.19003), center-exclusion for critical points
# (Rohleder, arXiv:2506.22184). Non-convex counterexamples: Burdzy-Werner
# (Annals 1999, two holes), Burdzy (Duke 2005, one hole). No simply connected
# counterexample is known.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./hot_spots.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Sparse P1 finite elements on polygonal meshes (numpy/scipy eigsh,
# shift-invert), exact rational geometry via sympy for mesh bookkeeping.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy sympy mpmath
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source papers (audit-verified ids only) ------------------------------
opentorus paper add https://arxiv.org/abs/2412.06344
opentorus paper add https://arxiv.org/abs/2506.22184
opentorus paper add https://arxiv.org/abs/1802.01800

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: The hot spots conjecture for planar convex domains

**Primary target (general).** For every bounded convex domain $\Omega \subset \mathbb{R}^2$,
every eigenfunction of the smallest nonzero Neumann Laplacian eigenvalue $\mu_2(\Omega)$
attains its maximum and its minimum on the boundary $\partial\Omega$. (Rauch 1974, in the
folklore form; the convex restriction is the standard surviving form after the
counterexamples below. Probabilistic reading: the hottest point of an insulated convex
plate moves to the boundary for large time.)

**Status audit (2026-08-17; independently counter-checked).** Fresh web check: the planar
convex case is **open**; no 2025/2026 proof claim exists. Dimension matters: in
sufficiently high dimension the convex statement is **refuted** — de Dios Pont
([arXiv:2412.06344](https://arxiv.org/abs/2412.06344), Dec 2024, still unpublished)
constructs smooth centrally symmetric convex bodies in $\mathbb{R}^d$, $d \ge d_0$
($d_0$ impractically large), whose second Neumann eigenfunction attains its maximum only
in the interior; the follow-up (arXiv:2508.16321) bounds how badly it can fail (ratio
$\to \sqrt e$). Settled planar classes: all triangles (Judge–Mondal, Annals 191 (2020)
with erratum Annals 195 (2022) fixing the acute case,
[arXiv:1802.01800](https://arxiv.org/abs/1802.01800); sharpened by Chen–Gui–Yao,
Invent. math. 244 (2026), arXiv:2311.12659: extrema at the endpoints of the longest
side); lip domains (Atar–Burdzy 2004; simplified by Rohleder, arXiv:2106.05224); convex
domains with two symmetry axes (Jerison–Nadirashvili 2000; higher-dimensional versions
Kennedy–Rohleder, arXiv:2410.00816); parallelograms unconditionally, kites and isosceles
trapezoids under hypotheses (arXiv:2604.19003); no interior critical point near the
"center" of a planar convex domain (Rohleder,
[arXiv:2506.22184](https://arxiv.org/abs/2506.22184)). Non-convex planar
counterexamples: with two holes (Burdzy–Werner, Annals 149 (1999)); with one hole
(Burdzy, Duke 129 (2005)); numerically also for one to five holes (Kleefeld,
arXiv:2101.01210 — floating-point, uncertified). No simply connected counterexample is
known. The conjecture's failure mode in high dimension makes the planar case a genuine
frontier, not a formality.

**Known partial results (classified, with sources).**
- Triangles, lip domains, two-axes symmetry, quadrilateral subclasses (KNOWN_RESULTs;
  cite parsed sources; keep the erratum history of the triangle proof visible).
- The high-dimensional refutation: CLAIMED/preprint (arXiv:2412.06344, no journal yet) —
  a KNOWN_RESULT only about the *general convex* statement in large $d$; it does not
  touch $d = 2$.
- Non-convex counterexamples with holes (KNOWN_RESULTs; journal sources; Kleefeld's
  numerics stay numerical evidence).
- Localization: extrema of the second eigenfunction within $c \cdot$ inradius of the
  boundary "tips" (Steinerberger, arXiv:1907.13044 — a localization, not a proof).

**START HERE — instance program first (mandatory).** Before any proof_write, in this
order:
1. write_file scripts/hotspots_fem.py — a hand-written P1 FEM Neumann eigensolver:
   triangulate a polygon (structured refinement of an initial triangulation; no external
   mesher), assemble stiffness/mass matrices (scipy.sparse), solve for the first few
   Neumann eigenpairs (eigsh, shift-invert near 0), locate argmax/argmin of the second
   eigenfunction, and report whether they are boundary vertices — with at least two
   refinement levels to show convergence, and BOTH eigenfunctions tested when
   $\mu_2$ is (near-)degenerate.
2. exp_new(title="Hot spots: FEM sweep over convex polygons",
   command="python scripts/hotspots_fem.py", environment="python-sci",
   run_from="workspace") then exp_run — sweep triangles (obtuse/right/acute), random
   convex quadrilaterals through octagons, and near-degenerate cases (near-squares,
   near-regular polygons); record extremum locations, boundary distances, and mesh
   convergence.
3. Any numeric "interior extremum" candidate must be treated as unverified until it
   survives refinement, both-eigenfunctions checks, and an interval/validated-numerics
   argument; submit only exactly checkable statements (e.g. symmetry-forced facts,
   rational eigenvalue enclosures where feasible) via proof_submit. Only ACCEPTED
   submissions are machine-checked.
A sketch without a single recorded instance run does not satisfy this dossier's task.

**Refutation track.** Negate: a counterexample is a single planar convex domain whose
second Neumann eigenfunction has an interior maximum. Search: FEM screening over
parametrized convex polygon families (the known non-convex mechanisms — bottlenecks,
holes — are forbidden by convexity; look at long thin domains, near-degenerate spectra,
high-eccentricity shapes); any candidate needs certified eigenvalue enclosures and a
$C^0$ eigenfunction bound (Liu–Oishi / Lehmann–Goerisch style) before it is anything
more than NUMERICAL_EVIDENCE. The planar-convex prior is strongly against success —
record the screening honestly. A verified counterexample claim must name the primary
claim in depends_on.

**Proof track.** Reproduce the settled classes numerically (triangles: extrema at the
endpoints of the longest side — check the sharpened form on the sweep); map where the
known techniques (coupling/lip, symmetry, center-exclusion) stop; test candidate
monotonicity lemmas on the FEM zoo; every unresolved inference is an explicit [GAP-n].

**Instance program (tools, not targets).** FEM eigenfunction geography over convex
polygons, convergence studies, degenerate-eigenvalue handling, boundary-distance
statistics. Numerics can only ever *support* the planar statement or flag candidates;
they can never prove it (uncountably many domains), and a candidate becomes a
counterexample only with validated numerics.

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
  --statement "For every bounded convex domain in the plane, every eigenfunction of the second Neumann eigenvalue of the Laplacian attains its maximum and minimum on the boundary."
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
