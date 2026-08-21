#!/usr/bin/env bash
# ============================================================================
# OpenTorus CALIBRATION example — Steinberg's conjecture (refuted 2016)
#
# KNOWN ground truth (see README.md): REFUTED. Cohen-Addad, Hebdige, Kral,
# Li, Salgado, "Steinberg's Conjecture is false", arXiv:1604.05108,
# JCTB 122 (2017) 452-456: a planar graph with no 4- or 5-cycles and no
# 3-coloring, built from gadgets (the paper presents it in figures; the
# reconstructed graph has 166 vertices / 300 edges). This run uses
# `prove --disprove`: the agent must find the refutation, RECONSTRUCT the
# counterexample from the paper's gadget description, and VERIFY all three
# properties mechanically (planarity, no 4-/5-cycles, UNSAT 3-colorability
# with a DRAT-certified SAT proof) - the COUNTEREXAMPLE_VERIFIED pathway.
# A run that reports the conjecture as open fails calibration on literature
# freshness; one that cites the refutation without a verified reconstruction
# stays at the (honest) literature-report level.
#
# Prerequisites: `opentorus` on PATH; Docker; a tool-calling model (defaults to
# a local Ollama server on :11434; override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./steinberg.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
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
# Graph handling (networkx: planarity, cycle checks) and SAT with proof
# logging (python-sat) for non-3-colorability certificates.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy sympy networkx python-sat
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper (audit-verified id) -------------------------------------
opentorus paper add https://arxiv.org/abs/1604.05108

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Steinberg's conjecture — find and verify a refutation

**Setup.** Steinberg conjectured (1976): every planar graph without cycles of length 4
and without cycles of length 5 is 3-colorable. (Compare Grötzsch's theorem: planar and
triangle-free implies 3-colorable — that one is true.)

**Task for this dossier (disprove mode).** Refute the conjecture by producing an explicit
planar graph with no 4-cycles, no 5-cycles, and chromatic number at least 4, via EITHER
route:

1. **Literature route.** Search for the known refutation and reconstruct the published
   counterexample. The construction is presented as a sequence of gadgets: a base gadget
   $G_1$ on 15 vertices with three contact vertices $a, b, c$ (no 3-coloring gives
   $a, b, c$ a common color), an intermediate gadget $G_2$ from three copies of $G_1$
   glued to a triangle, and the final graph from four copies of $G_2$. Reconstruct the
   graph edge by edge from the paper; use the paper's lemmas as transcription checksums
   (each gadget's coloring property is itself a small exact SAT check — if a lemma check
   fails, an edge was mistranscribed).
2. **Direct search route.** Hunt a counterexample yourself: generate planar graphs
   without 4-/5-cycles (girth-constrained planar triangulation-like generators, gadget
   amplification) and test 3-colorability by SAT. Any hit is a finite certificate.

Either way, **verify** the candidate mechanically, with each property as its own
recorded check:
- planarity (certified planar embedding),
- absence of 4- and 5-cycles (exhaustive short-cycle enumeration),
- non-3-colorability: SAT encoding of 3-coloring, UNSAT with a machine-checkable
  proof (DRAT/DRUP logged and re-checked), or an exact exhaustive argument.
Record it through the proper verification pathway (COUNTEREXAMPLE_VERIFIED needs an
explicit verification record; a floating claim "the paper says so" is not a verification).

**Report honestly what remains open afterwards.** The refutation does not close the
area: the Bordeaux conjecture (planar, no 5-cycles, no *intersecting* triangles implies
3-colorable) remains open; planar graphs without cycles of length 4–7 (and 4–8, 4–9)
ARE 3-colorable (known results); the cases "no cycles of length 4–6" and the exact
strength of the refuted statement's neighborhood are still active. The published
counterexample is not claimed minimal — the authors mention smaller, unpublished ones
(85 vertices); the minimum order is unknown.

**Honesty requirements.** A graph that fails any of the three checks is a candidate,
not a counterexample. The refutation's publication venue and year are cited from the
parsed PAPER-* artifact, not from memory. Statements about what remains open cite
sources or are marked as this dossier's own conjectures.
NOTES
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Refutation run ------------------------------------------------------
# `prove` gates on the honesty linter: a report that still overclaims exits non-zero.
# That is a finding to read, not a crash — but under `set -e` it aborted this driver
# right here, before the report/verdict/PDF steps below ever ran. Keep the signal,
# finish the workflow, and exit with it at the end.
PROVE_RC=0
opentorus --verbose prove "${TARGET}" --disprove --min-papers 2 || PROVE_RC=$?

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint || true   # advisory: warnings are findings to read, not a reason to skip the verdict
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
echo "Calibration check: an explicit planar, C4/C5-free, non-3-colorable graph,"
echo "all three properties machine-verified (planarity + cycle enumeration + UNSAT"
echo "certificate), recorded as COUNTEREXAMPLE_VERIFIED; the report must credit the"
echo "2016/17 refutation (Cohen-Addad et al., JCTB 122) and keep the Bordeaux"
echo "conjecture and the minimum-counterexample question honestly open."

exit "${PROVE_RC}"
