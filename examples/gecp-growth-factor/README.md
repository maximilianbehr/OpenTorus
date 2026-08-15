# The growth factor of Gaussian elimination with complete pivoting

## Open problem

For a nonsingular $A \in \mathbb{R}^{n\times n}$, the growth factor of Gaussian elimination
with complete pivoting is $g(A) = \max_{i,j,k}|a^{(k)}_{ij}| / \max_{i,j}|a_{ij}|$, and
$g(n) = \sup_A g(A)$. Wilkinson's 1961 question is still open: **is $g(n)$ polynomial in $n$?**
Exact values are known only for $n \le 4$ ($1, 2, 2.25, 4$) — **even $g(5)$ is unknown**.

Status (August 2026): the best upper bound is $n^{0.2079\ln n + 0.91}$
([Bisain–Edelman–Urschel, arXiv:2312.00994](https://arxiv.org/abs/2312.00994)), the first
improvement on Wilkinson's bound in over sixty years. Cryer's conjecture $g(n) \le n$ was
disproved at $n=13$ (Gould 1991). Numerical optimization by
[Edelman–Urschel (SIMAX 2024, arXiv:2303.04892)](https://arxiv.org/abs/2303.04892) suggests
$g(n) > n$ exactly for $n \ge 11$.

## What this runs

`gecp_growth_factor.sh` follows the standard example workflow: fresh workspace →
model/agent config (`max_steps inf`, `permissions.mode trusted`) → `python-sci` container
(numpy, scipy, mpmath, sympy) → `paper add` for the two source papers → dossier from an
inline `notes.md` → `opentorus prove --min-papers 5` → honesty-linted report + PDF export.

The problem is picked for OpenTorus's verification stack: a candidate record-growth matrix
is a *finite certificate*. The agent can re-run the elimination in interval arithmetic and
submit the enclosure via `proof_submit(backend="interval")` — the interval verifier is
enabled by default — so a numerical discovery can become a `PROOF-*` verification artifact
instead of a floating-point anecdote.

## Prerequisites

- **Docker** for the `python-sci` container.
- **A tool-calling model** — defaults to a local Ollama model on port 11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash gecp_growth_factor.sh
```

## Honesty note

Nobody expects a local model to settle Wilkinson's question. Honest, useful outcomes are:
a literature-grounded status sketch; reproduction of known lower-bound optimization runs at
small $n$; and — best case — an interval-certified growth lower bound for a concrete matrix,
recorded as a verification artifact. Floating-point growth values alone remain
support-only evidence and are never upgraded to verified claims.

## Selected references

- A. Edelman, J. Urschel (2024), *Some New Results on the Maximum Growth Factor in Gaussian
  Elimination*, SIMAX 45(2). [arXiv:2303.04892](https://arxiv.org/abs/2303.04892)
- A. Bisain, A. Edelman, J. Urschel (2024), [arXiv:2312.00994](https://arxiv.org/abs/2312.00994)
- J. H. Wilkinson (1961), *Error analysis of direct methods of matrix inversion*, J. ACM 8.
- N. Gould (1991), *On growth in Gaussian elimination with complete pivoting*, SIMAX 12.
