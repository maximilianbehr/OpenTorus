# Polynomial Hirsch Conjecture — literature-honest dossier

## Open problem

The Polynomial Hirsch Conjecture asks whether there exists a polynomial `p(n, d)` that bounds
the combinatorial (graph) diameter of every `d`-dimensional convex polytope with `n` facets.
The original Hirsch bound `n - d` was disproven (Santos, 2010), but whether the diameter is
bounded by *some* polynomial in `n` and `d` remains open — a central question in polyhedral
combinatorics and the theory of the simplex method. This example builds a citation-honest
literature dossier **plus containerized polymake experiments**: exact graph-diameter
computations for concrete polytopes, reproduction of known records (Santos 2010,
Matschke–Santos–Weibel), and a spindle search — a `d`-dimensional spindle with length `> d`
violates the `d`-step property and seeds Hirsch-violating constructions, and each candidate
is a finite, exactly checkable certificate. A *polynomial*-Hirsch counterexample is an
infinite family, so sweeps only ever support; the report asserts no resolution.

## What this runs

The driver `poly_hirsch_sota.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`, `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
3. **Prepare the polymake container** — `opentorus env prepare polymake` from a Dockerfile
   (`debian:trixie-slim` + the Debian `polymake` package; smoke-tested with
   `polymake --no-config 'print cube(4)->GRAPH->DIAMETER;'` → `4`). The agent runs
   polymake scripts via `exp_new(..., environment='polymake')`.
4. **Add the source paper** — Santos's Hirsch counterexample,
   [arXiv:1006.2814](https://arxiv.org/abs/1006.2814).
5. **Create the dossier** — `opentorus problem new` with the conjecture, the honest scope of
   numerics (certified diameters, spindle search, record reproduction), and tags.
6. **Prove** — `opentorus prove PROBLEM-0001 --min-papers 10` (literature → proof draft → gap-fill).
7. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

Generated report text cites only locally stored `PAPER-*` artifacts; missing metadata is marked
missing, never invented.

## Prerequisites

- **Docker** — for the `polymake` container.
- **A tool-calling model** — the script defaults to a local Ollama model on port 11434 (`muse-glimmer:30b`); override with `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL` or edit the `opentorus config set model.*` lines.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash poly_hirsch_sota.sh
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. The generated report is checked by the artifact-aware honesty linter.
