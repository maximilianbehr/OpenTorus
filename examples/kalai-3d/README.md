# Kalai's 3^d conjecture

## Open problem

Does every centrally symmetric $d$-dimensional polytope have at least $3^d$ nonempty faces
(all dimensions counted, the polytope itself included)? Hanner polytopes attain exactly
$3^d$. Proved for $d \le 4$ by
[Sanyal–Werner–Ziegler (arXiv:0708.3661)](https://arxiv.org/abs/0708.3661) — who in the same
paper refuted Kalai's stronger conjectures B and C — and **open for every $d \ge 5$**
($3^5 = 243$). The conjectured extremizers coincide with those of Mahler's volume
conjecture, an unproven but suggestive parallel.

## What this runs

`kalai_3d.sh` follows the standard example workflow (fresh workspace → config → container →
source paper → dossier → `opentorus prove --min-papers 5` → honesty-linted report + PDF).
The agent can run exact face-lattice computations for concrete centrally symmetric
5-polytopes as `EXP-*` experiments: the face count of a vertex list is finite combinatorics
in rational arithmetic, so both reproductions (Hanner minimizers hit 243 exactly) and any
candidate violation are exactly checkable certificates.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults: local Ollama on 11434, override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`). The script resets `.opentorus/`.

## Run

```bash
bash kalai_3d.sh
```

## Honesty note

The refutation of Kalai's own stronger conjectures B and C in the very paper that proved
$d \le 4$ is the cautionary tale this dossier should keep in view: plausible-looking
strengthenings fail. Search sweeps in $d=5$ that find nothing below 243 are support-only;
a candidate below 243 is a counterexample only after its face lattice is recomputed exactly.

## Selected references

- G. Kalai (1989), *The number of faces of centrally-symmetric polytopes*, Graphs Combin. 5.
- R. Sanyal, A. Werner, G. M. Ziegler (2009), Discrete Comput. Geom. 41.
  [arXiv:0708.3661](https://arxiv.org/abs/0708.3661)
- O. Hanner (1956), *Intersections of translates of convex bodies*, Math. Scand. 4.
