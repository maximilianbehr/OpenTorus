# Campaign: Smale's mean value conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — every polynomial, every point; fixed
> polynomials and degree-wise searches are internal tools. The driver designates the
> primary claim deterministically.

## The problem

For every complex polynomial $p$ of degree $d \ge 2$ and every $z$ with $p'(z) \ne 0$,
some critical point $\zeta$ satisfies $|p(z)-p(\zeta)| \le K\,|z-\zeta|\,|p'(z)|$ with
$K = 1$ (Smale 1981, from his work on the complexity of root finding). Sharp conjectured
constant: $K = (d-1)/d$, attained by $z^d - dz$. Smale's original proof gives $K \le 4$;
closing the factor 4 has been open for 45 years.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** All arXiv proof claims unaccepted (Schmieder 2002 unpublished; Wang 2017
withdrawn; Ma–Ma 2022 unpublished). Bound ladder: $4^{(d-2)/(d-1)}$ (Beardon–Minda–Ng
2002), $4\frac{d-1}{d+1}$ (Conte–Fujikawa–Lakic 2007), $4 - 2.263/\sqrt d$ for $d \ge 8$
(Crane 2007). Sharp for $d \le 4$ (Tischler 1989 line) and $d = 5$ (Crane, CMFT 2006,
published computational proof; $M_5 = 4/5$); $6 \le d \le 10$ is numerical only
(Marinov–Sendov 2007). The active frontier is the **dual** conjecture
($\max_\zeta |p(\zeta)/\zeta| \ge 1/d$; Dubinin–Sugawa,
[arXiv:0906.4605](https://arxiv.org/abs/0906.4605)): proved $d \le 7$
(Hinkkanen–Kayumov–Khammatova, [arXiv:2303.17586](https://arxiv.org/abs/2303.17586),
Constr. Approx. 61 (2025)), odd polynomials (2025); general bounds $1/4^d$ (Ng–Zhang,
[arXiv:1609.00170](https://arxiv.org/abs/1609.00170)), $\frac1d\tan(\pi/(4d))$ and later
$1/d^2$ (Dubinin — the best universal dual bound). Not this problem: Sendov's conjecture
(see [calibration-sendov](../calibration-sendov/)) and the $\mathrm{Diff}(S^3)$ Smale
conjecture.

## What this runs

`smale_mean_value.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with sympy/mpmath → three audit-verified papers → dossier →
**driver-created primary claim** + `verdict --set-primary` → `prove --min-papers 5` →
report + lint → `problem verdict` → PDF.

Dual track: the refutation side searches the critical-point parametrization (fix the
$d-1$ critical points, integrate to get $p$) for polynomials with
$\min_\zeta |p(\zeta)/\zeta| > (d-1)/d$ (refutes the sharp form) or $> 1$ (refutes
Smale) — for a fixed rational $p$ this is a finite, certifiable computation via root
isolation and interval bounds; the proof track verifies the extremal family exactly
($S(z^d - dz) = (d-1)/d$ via `proof_submit`), maps the search landscape around it, and
tests lemma candidates borrowed from the dual-conjecture technology.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact extremal-family certificates, certified $S(p)$ enclosures for
sampled polynomials, landscape statistics, and a status sketch that keeps the unaccepted
proof claims, the numerical $d \le 10$ evidence, and the theorem layer apart —
`NUMERICAL_EVIDENCE` / `COMPUTATIONAL_EVIDENCE`, not a resolution. Floating-point minima
over critical points are candidates; only certified enclosures count.

## Selected references

- S. Smale (1981), *The fundamental theorem of algebra and complexity theory*,
  Bull. AMS 4.
- A. F. Beardon, D. Minda, T. W. Ng (2002), *Smale's mean value conjecture and the
  hyperbolic metric*, Math. Ann. 322.
- E. Crane (2007), *A bound for Smale's mean value conjecture for complex polynomials*,
  Bull. LMS 39.
- Dubinin–Sugawa: [arXiv:0906.4605](https://arxiv.org/abs/0906.4605); Ng–Zhang:
  [arXiv:1609.00170](https://arxiv.org/abs/1609.00170); Hinkkanen–Kayumov–Khammatova:
  [arXiv:2303.17586](https://arxiv.org/abs/2303.17586).
