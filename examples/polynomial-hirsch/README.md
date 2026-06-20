# Polynomial Hirsch Conjecture — literature-honest dossier

## Open problem

The Polynomial Hirsch Conjecture asks whether there exists a polynomial `p(n, d)` that bounds
the combinatorial (graph) diameter of every `d`-dimensional convex polytope with `n` facets.
The original Hirsch bound `n - d` was disproven (Santos, 2010), but whether the diameter is
bounded by *some* polynomial in `n` and `d` remains open — a central question in polyhedral
combinatorics and the theory of the simplex method. This example builds a **literature-only**
dossier: it collects and cites prior work and assembles a citation-honest report, running no
numerical experiments and asserting no resolution.

## What this runs

The driver `poly_hirsch_sota.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`, `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
3. **Create the dossier** — `opentorus problem new` with the conjecture stated inline, a domain, and the tags `hirsch` and `polytope-diameter`, then `opentorus problem show`.
4. **Prove** — `opentorus prove PROBLEM-0001 --min-papers 10` (literature → proof draft → gap-fill); at least 10 paper artifacts must be gathered before drafting.
5. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

Generated report text cites only locally stored `PAPER-*` artifacts; missing metadata is marked
missing, never invented.

## Prerequisites

- **A tool-calling model** — the script targets a local Ollama model on port 11435 (`gpt-oss:120b`); set `model.provider`, `model.name`, and `model.base_url` for your own setup.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash poly_hirsch_sota.sh
```

## Honesty note

Numerical experiments and proof sketches only *support* a claim; only a verification artifact
verifies one. The generated report is checked by the artifact-aware honesty linter.
