# Lehmer's Mahler measure problem

## Open problem

Is $\inf\{M(p) : p \in \mathbb{Z}[x] \text{ monic}, M(p) > 1\}$ strictly greater than 1?
Here $M(p) = \prod_i \max(1,|\alpha_i|)$ is the Mahler measure. Lehmer asked in 1933; his
degree-10 polynomial with $M \approx 1.176280818$ is still the record. Smyth (1971) settled
the nonreciprocal case ($M \ge 1.3247\ldots$), Dobrowolski (1979) gives the best general
lower bound $1 + c(\log\log d/\log d)^3$ — the uniform gap is **open** (survey:
[Smyth, arXiv:math/0701397](https://arxiv.org/abs/math/0701397)).

## What this runs

`lehmer.sh` follows the standard example workflow (fresh workspace → config → container →
source paper → dossier → `opentorus prove --min-papers 5` → honesty-linted report + PDF).
The numerics angle: Mahler measures of concrete polynomials admit **certified interval
enclosures** (isolate roots, multiply interval magnitudes), so family sweeps become scoped,
machine-checked statements via `proof_submit(backend="interval")` — "no measure in
$(1, 1.17628)$ in family F up to degree D" — rather than uncertified tables.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults: local Ollama on 11434, override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`). The script resets `.opentorus/`.

## Run

```bash
bash lehmer.sh
```

## Honesty note

Ninety years of searches finding nothing below Lehmer's record is famous — and famously not
a proof. Every certified sweep in this dossier carries its family-and-degree scope in the
claim text; the linter's job is to keep "verified for family F, degree ≤ D" from drifting
into "verified".

## Selected references

- D. H. Lehmer (1933), Ann. of Math. 34.
- C. Smyth (1971), *On the product of the conjugates outside the unit circle of an algebraic
  integer*, Bull. LMS 3; survey (2007): [arXiv:math/0701397](https://arxiv.org/abs/math/0701397)
- E. Dobrowolski (1979), Acta Arith. 34.
