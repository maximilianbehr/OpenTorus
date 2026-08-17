# Campaign: The Erdős–Straus conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every $n \ge 2$; individual $n$, ranges, and
> residue classes are internal tools. The driver designates the primary claim
> deterministically.

## The problem

For every integer $n \ge 2$ there are positive integers $x, y, z$ with
$4/n = 1/x + 1/y + 1/z$ (Erdős–Straus, 1948). Egyptian-fraction number theory at its most
elementary-looking: it reduces to primes, most residue classes are dispatched by
polynomial identities, and the six square classes mod 840 are where every identity-based
approach provably stops.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** A February 2026 claimed full proof ([arXiv:2602.11774](https://arxiv.org/abs/2602.11774))
is publicly doubted and unaccepted; the other 2024–2026 arXiv "proofs" are partial,
heuristic, or conditional. Verified for all $n \le 10^{17}$ (Salez 2014,
[arXiv:1406.6307](https://arxiv.org/abs/1406.6307)); a 2025 preprint claims $10^{18}$
([arXiv:2509.00128](https://arxiv.org/abs/2509.00128), unrefereed, though adopted by
erdosproblems.com). Polynomial identities cover every primitive class mod 840 except
$n \equiv 1, 121, 169, 289, 361, 529$ (Mordell / Yamamoto / Rosati); the
Schinzel/Yamamoto obstruction shows a square class $n \equiv r^2 \pmod q$ can never be
covered by an identity, so no finite identity system can close the problem (derived in
Elsholtz–Tao, [arXiv:1107.1010](https://arxiv.org/abs/1107.1010)). Exceptions have
density zero (Vaughan 1970). For $m/n$, Schinzel *conjectured* solvability above a
threshold $n_0(m)$; any such threshold is at least $\exp(m^{1/3+o(1)})$
(Pomerance–Weingartner, [arXiv:2511.16817](https://arxiv.org/abs/2511.16817)).

## What this runs

`erdos_straus.sh` follows the campaign template: fresh workspace → config (timeout 2400s)
→ container with sympy/gmpy2/z3 → three audit-verified papers → dossier → **driver-created
primary claim** + `verdict --set-primary` → `prove --min-papers 5` → report + lint →
`problem verdict` → PDF.

Dual track: the refutation side hunts a fixed $n$ without a representation (for a fixed
$n$ this is a finite, exactly checkable statement — the certificate shape is clear even if
the search cannot reach new territory beyond $10^{17}$); the proof track reproduces the
residue-class identity system, certifies each identity via `proof_submit` (sympy), maps
the CRT coverage of $\mathbb{Z}/840$, and confronts the Schinzel obstruction on the parsed
source.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: an exhaustively verified range with its bound stated, a set of
machine-checked polynomial identities and their exact coverage, a correctly classified
literature map (refereed vs. claimed) — `COMPUTATIONAL_EVIDENCE`, not a resolution.
Density-zero exceptions and $10^{17}$ of verification set a strong prior; the campaign
treats a failed counterexample search as exactly that.

## Selected references

- P. Erdős (1950), *Az 1/x₁ + … + 1/xₙ = a/b egyenlet egész számú megoldásairól*, Mat. Lapok 1.
- L. J. Mordell (1969), *Diophantine Equations*, Ch. 30.
- R. C. Vaughan (1970), *On a problem of Erdős, Straus and Schinzel*, Mathematika 17.
- C. Elsholtz, T. Tao, *Counting the number of solutions to the Erdős–Straus equation on
  unit fractions*: [arXiv:1107.1010](https://arxiv.org/abs/1107.1010).
- S. E. Salez, *The Erdős–Straus conjecture: new modular equations and checking up to
  N = 10^17*: [arXiv:1406.6307](https://arxiv.org/abs/1406.6307).
- C. Pomerance, A. Weingartner: [arXiv:2511.16817](https://arxiv.org/abs/2511.16817).
