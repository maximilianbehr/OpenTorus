#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Polynomial Hirsch Conjecture (literature + polymake)
# Source: a classical open problem in polyhedral combinatorics
#
# A literature-honest dossier PLUS containerized polymake experiments: the agent
# gathers and cites prior work, and can compute exact graph diameters of
# concrete polytopes (spindle search, record reproduction) inside a pinned
# polymake container.
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. build the polymake container (Debian package; exact diameter computations)
#   4. register Santos's Hirsch counterexample paper as a local PAPER-* artifact
#   5. write the problem statement to notes.md and create the dossier
#   6. run `opentorus prove --min-papers 10` (literature -> proof draft -> gap-fill)
#   7. build an honesty-linted report and export a PDF
#
# Prerequisites:
#   - `opentorus` on PATH (activate the env where you installed it)
#   - Docker, for the polymake container
#   - a tool-calling model; this script targets a local Ollama server on :11434 (override with OPENTORUS_MODEL / OPENTORUS_BASE_URL)
#
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./poly_hirsch_sota.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# Activate the env where you installed OpenTorus so `opentorus` is on PATH, e.g.:
#   source ~/GITHUB/OpenTorus/.venv/bin/activate

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
# Edit these for your provider/model. Defaults: a local Ollama model on :11434 (override with OPENTORUS_MODEL / OPENTORUS_BASE_URL).
opentorus config set model.provider ollama
opentorus config set model.name "${OPENTORUS_MODEL:-muse-glimmer:30b}"              # or: gemma4:31b, gpt-4o-mini, …
opentorus config set model.base_url "${OPENTORUS_BASE_URL:-http://localhost:11434}"
opentorus config set model.timeout_seconds 2400         # survives temporary CPU-offload of the model
opentorus config set agent.style autonomous            # fewer prompts; destructive ops still confirmed
opentorus config set agent.max_steps inf               # no overall step cap (Ctrl-C to stop)
opentorus config set agent.prove_gap_fill_max_steps inf  # no separate gap-fill cap
opentorus config set permissions.mode trusted          # auto-allow low/medium-risk actions

# --- 3. Numerical experiment environment ------------------------------------
# polymake computes exact combinatorial data of polytopes — GRAPH->DIAMETER,
# face lattices, spindle widths — from V- or H-descriptions. Smoke-tested:
# `polymake --no-config 'print cube(4)->GRAPH->DIAMETER;'` -> 4.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends polymake python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
DOCKERFILE
opentorus env prepare polymake --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
# Santos's counterexample to the (original) Hirsch conjecture — the blueprint
# for spindle-based lower-bound constructions.
opentorus paper add https://arxiv.org/abs/1006.2814

# --- 5. Problem statement & dossier -----------------------------------------
cat > notes.md << 'NOTES'
# Problem: Polynomial Hirsch Conjecture

Does there exist a polynomial p(n, d) that bounds the combinatorial (graph) diameter of every
d-dimensional convex polytope with n facets? The original Hirsch bound n - d was disproven
(Santos, 2010, [arXiv:1006.2814](https://arxiv.org/abs/1006.2814)), but whether the diameter
is bounded by *some* polynomial in n and d remains open — a central question in polyhedral
combinatorics and the theory of the simplex method for linear programming.

**What a refutation would take — and what numerics can honestly contribute.** A
counterexample to *polynomial* Hirsch is an infinite family with superpolynomially growing
diameter; no single computation refutes the conjecture. What exact computation CAN do:

1. **Certified diameters.** For concrete polytopes (V- or H-description), polymake computes
   the graph and its diameter exactly. Every computed value is a reproducible EXP-* record.
2. **Spindle search (the Santos route).** A d-dimensional spindle (two vertices whose facet
   sets partition all n facets) with length > d violates the d-step property and seeds
   Hirsch-violating constructions. Santos's original example: a 5-dimensional spindle with
   48 facets. Finding a *new, smaller* spindle with length > d — or a family suggesting
   growing excess — is a genuine, publishable contribution and a finite, checkable object.
3. **Record reproduction.** Reproduce known diameter records (Santos 2010; the smaller
   counterexamples of Matschke–Santos–Weibel) from their published descriptions, as
   ground-truth checks of the pipeline.

**Experiments.** Use the `polymake` environment (exp_new with environment='polymake'):
write polymake scripts (perl) under scripts/, e.g.
`my $p = cube(4); print $p->GRAPH->DIAMETER;`, and run them via
`exp_new(title=..., command='polymake --no-config --script scripts/foo.pl',
environment='polymake', run_from='workspace')` then exp_run. Construct candidate spindles
from V-descriptions (`new Polytope(POINTS=>...)`), check the spindle property via the two
vertices' facet incidences, and record length and dimension. Sweeps that find nothing are
support-only; a found spindle with length > d is a finite certificate to re-verify exactly.

Tags: polyhedral combinatorics, polytope diameter, simplex method, spindles.
NOTES
# `--structured` maps the single top-level '# ' heading to one dossier (PROBLEM-0001).
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
# The prove loop gathers and cites local papers and assembles a citation-honest
# report; it asserts no resolution. Reports cite only local PAPER-* artifacts, and
# missing bibliographic metadata is marked missing, never invented. --min-papers
# gates report building on gathering at least N local papers first.
opentorus --verbose prove "${TARGET}" --min-papers 10

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint            # honesty linter flags overclaiming
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
