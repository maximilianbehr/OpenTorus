# Campaign: The Erdős–Szekeres "happy ending" conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — $ES(n) = 2^{n-2}+1$ for every $n$; single
> values (including the ES(7) frontier) are internal tools. The driver designates the
> primary claim deterministically.

## The problem

Every $2^{n-2} + 1$ points in general position in the plane contain $n$ points in convex
position — the conjectured exact value of the Erdős–Szekeres function from the 1935
"happy ending" paper. Named by Erdős for the marriage of George Szekeres and Esther Klein,
whose $ES(4) = 5$ observation started it.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open** (Erdős problem #107, \$500; \$1000 by Graham). Known exactly: $ES(3..6) =
3, 5, 9, 17$ — $ES(6)$ by Szekeres–Peters 2006 (~1500 CPU-h), re-verified by SAT orders
of magnitude cheaper (Marić 2019 with Isabelle/HOL; Scheucher ~1 CPU-h; Heule–Scheucher
encoding, 8.53 CPU-s, [arXiv:2403.00737](https://arxiv.org/abs/2403.00737)).
$ES(7) = 33$ open: the stronger Peters–Szekeres form was SAT-refuted (Balko–Valtr 2017);
UNSAT certificates exist only for anchored subfamilies of 33-point sets
(arXiv:2512.24061, Dec 2025). Upper bounds: Suk $2^{n+O(n^{2/3}\log n)}$
([arXiv:1604.08657](https://arxiv.org/abs/1604.08657), JAMS 2017), then
Holmsen–Mojarrad–Pach–Tardos $2^{n+O(\sqrt{n\log n})}$
([arXiv:1710.11415](https://arxiv.org/abs/1710.11415), JEMS 2020) — still the best.
Baek–Balko (SoCG 2025 / JCTA 2026): "split $k$-gons" appear at $2^{k-2}+1$ points
(tight), conjecture holds for decomposable sets. Distinct problem, do not conflate: the
empty-hexagon number $h(6) = 30$ (Heule–Scheucher 2024, Lean-verified pipeline).

## What this runs

`happy_ending.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with sympy/python-sat → three audit-verified papers → dossier →
**driver-created primary claim** + `verdict --set-primary` → `campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) →
report + lint → `problem verdict` → PDF.

Dual track: the refutation side searches for 33 points with no convex heptagon — SAT over
signotope axioms gives *abstract* witnesses that must then be realized by integer
coordinates (realizability is the honest second step); the proof track re-derives
$ES(6) = 17$ as an UNSAT certificate, verifies the classical $2^{n-2}$-point
constructions exactly (integer orientation determinants via `proof_submit`), and attacks
anchored 33-point subfamilies as lemmas.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exactly verified constructions, a cheap certified re-derivation of
$ES(6) = 17$, partial anchored-subfamily results at 33 points — `COMPUTATIONAL_EVIDENCE`,
not a resolution. An abstract SAT witness is not a point set; the dossier keeps
"abstract order type" and "realized configuration" apart, and full ES(7) UNSAT is known
to be out of current reach.

## Selected references

- P. Erdős, G. Szekeres (1935), *A combinatorial problem in geometry*, Compositio Math. 2;
  (1960/61), *On some extremum problems in elementary geometry*, Ann. Univ. Sci. Budapest.
- G. Szekeres, L. Peters (2006), *Computer solution to the 17-point Erdős–Szekeres
  problem*, ANZIAM J. 48.
- A. Suk: [arXiv:1604.08657](https://arxiv.org/abs/1604.08657) (JAMS 2017);
  Holmsen–Mojarrad–Pach–Tardos: [arXiv:1710.11415](https://arxiv.org/abs/1710.11415)
  (JEMS 2020).
- M. Heule, M. Scheucher: [arXiv:2403.00737](https://arxiv.org/abs/2403.00737)
  (h(6)=30 + the fast ES(6) encoding); M. Balko, P. Valtr (2017), EJC 66.
