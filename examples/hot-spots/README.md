# Campaign: The hot spots conjecture (planar convex case)

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified statement — every bounded convex planar domain; individual
> polygons and FEM sweeps are internal tools. The driver designates the primary claim
> deterministically.

## The problem

For every bounded convex domain in the plane, every second-Neumann-eigenvalue
eigenfunction attains its extrema on the boundary (Rauch 1974; the "hottest point of an
insulated plate moves to the boundary"). The first PDE/spectral-theory example in the
collection.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Planar convex case open**; dimension now matters. In sufficiently high dimension the
convex statement is **refuted** by a still-unpublished Dec 2024 preprint (de Dios Pont,
[arXiv:2412.06344](https://arxiv.org/abs/2412.06344): smooth, centrally symmetric convex
bodies with interior-only maximum; failure ratio $\to \sqrt e$, arXiv:2508.16321). Settled
planar classes: all triangles (Judge–Mondal, Annals 2020 + erratum 2022,
[arXiv:1802.01800](https://arxiv.org/abs/1802.01800); sharpened by Chen–Gui–Yao,
Invent. math. 244 (2026)); lip domains (Atar–Burdzy 2004); two symmetry axes
(Jerison–Nadirashvili 2000); parallelograms, kites/trapezoids under hypotheses
(arXiv:2604.19003); center-exclusion for interior critical points (Rohleder,
[arXiv:2506.22184](https://arxiv.org/abs/2506.22184)). Non-convex counterexamples exist
with two holes (Burdzy–Werner, Annals 1999) and one hole (Burdzy, Duke 2005); none simply
connected. No 2025/2026 proof claim for the planar convex case.

## What this runs

`hot_spots.sh` follows the campaign template: fresh workspace → config (timeout 2400s) →
container with numpy/scipy/sympy → three audit-verified papers → dossier →
**driver-created primary claim** + `verdict --set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) →
report + lint → `problem verdict` → PDF.

Dual track: the refutation side screens convex polygon families with a hand-written P1
FEM Neumann eigensolver (shift-invert `eigsh`, refinement studies, both eigenfunctions on
near-degenerate spectra) for interior extrema — with the explicit bar that a candidate
counts only after validated numerics (certified eigenvalue enclosures + $C^0$ bounds);
the proof track reproduces the settled classes on the sweep (triangles: extrema at the
endpoints of the longest side) and maps where coupling, symmetry, and center-exclusion
techniques stop.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: an eigenfunction-geography atlas over convex polygons with
convergence data, reproduced settled classes, a correctly layered literature map
(published theorems / the unpublished high-dimensional refutation / uncertified
numerics) — `NUMERICAL_EVIDENCE`, not a resolution. FEM extrema are floating-point
statements; the dossier treats every interior-extremum sighting as a candidate until
certified, and the planar-convex prior is strongly against one.

## Selected references

- J. Rauch (1974), lecture, Tulane; B. Kawohl (1985), *Rearrangements and convexity of
  level sets in PDE* (the conjecture's written sources).
- R. Bañuelos, K. Burdzy (1999), JFA 164; K. Burdzy, W. Werner (1999), Annals 149;
  K. Burdzy (2005), Duke 129.
- C. Judge, S. Mondal: [arXiv:1802.01800](https://arxiv.org/abs/1802.01800) (Annals 2020;
  erratum 2022); Chen–Gui–Yao: arXiv:2311.12659 (Invent. math. 2026).
- J. de Dios Pont: [arXiv:2412.06344](https://arxiv.org/abs/2412.06344);
  J. Rohleder: [arXiv:2506.22184](https://arxiv.org/abs/2506.22184) and the survey
  arXiv:2404.01890.
