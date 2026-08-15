# The Marcus–de Oliveira determinantal conjecture

## Open problem

For normal $A, B \in \mathbb{C}^{n\times n}$ with eigenvalues $a_i$, $b_i$, the conjecture of
Marcus (1972) and de Oliveira (1982) asserts
$$
\det(A + UBU^*) \;\in\; \operatorname{conv}\Bigl\{\prod_i \bigl(a_i + b_{\sigma(i)}\bigr) : \sigma \in S_n\Bigr\}
\quad\text{for every unitary } U.
$$
Known for $n \le 3$ and for essentially Hermitian matrices; **open in general for every
$n \ge 4$** — even the subcase $n=4$, $A$ Hermitian, $B$ normal, after 50+ years
(survey: [Mathematics 13(5):711, 2025](https://doi.org/10.3390/math13050711); recent special
cases: [arXiv:2006.14846](https://arxiv.org/abs/2006.14846)).

## What this runs

`marcus_de_oliveira.sh` follows the standard example workflow (fresh workspace → config →
`python-sci` container → source paper → dossier → `opentorus prove --min-papers 5` →
honesty-linted report + PDF).

This example is a designated **counterexample-verification** target. The conjectured hull is
a polygon in the plane; membership of $\det(A + UBU^*)$ is a tiny LP, and the search over
$U(n)$ is smooth multi-start optimization the agent can run as `EXP-*` experiments. A
genuine violation is a single machine-checkable witness — one $(A, B, U)$ triple plus a
separating hyperplane, certifiable in exact/interval arithmetic — which is exactly the
`COUNTEREXAMPLE_VERIFIED` pathway in the dossier model.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults: local Ollama on 11434, override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`). The script resets `.opentorus/`.

## Run

```bash
bash marcus_de_oliveira.sh
```

## Honesty note

Sweeps that find no violation are *support* for the conjecture, never proof; the report
linter keeps that distinction. Conversely, a floating-point "violation" is not a
counterexample until the exact certificate passes — near-boundary points are exactly where
rounding lies. Failed candidate certificates are preserved as first-class artifacts.

## Selected references

- G. N. de Oliveira (1982), *Normal matrices (research problem)*, Linear Multilinear Algebra 12.
- M. Marcus (1972), *Derivations, Plücker relations, and the numerical range*, Indiana Univ. Math. J. 22.
- *A class of normal dilation matrices affirming the conjecture* (2020),
  [arXiv:2006.14846](https://arxiv.org/abs/2006.14846)
- *Revisiting the Marcus–de Oliveira Conjecture* (2025), Mathematics 13(5):711.
