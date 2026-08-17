# Campaign: How many deviations? The discrepancy of ±1 matrices

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — an infinite family of sign matrices with
> discrepancy $\ge (1+\delta)\sqrt n$; exact small-$n$ records and structured families are
> internal tools. The driver designates the primary claim deterministically.
>
> Source: [Randomstrasse101](https://randomstrasse101.math.ethz.ch/posts/HowManyDeviations/)
> (ETH Zürich open-problems blog), Problems 11–12; archived with Updates as
> [arXiv:2504.20539](https://arxiv.org/abs/2504.20539). Sibling of
> [calibration-sylvester-discrepancy](../calibration-sylvester-discrepancy/) (Conjecture 13,
> refuted) and [komlos-conjecture](../komlos-conjecture/) (Problem 10).

## The problem

Spencer's "six standard deviations suffice" says every $n \times n$ $\pm1$ matrix has a
sign vector $x$ with $\lVert Ax\rVert_\infty \le 6\sqrt n$. How many deviations are really
needed? Open Problem 11 asks for the exact constant; Conjecture 12 asks whether it is
strictly more than one — is there an infinite family with $\mathrm{disc}(A) \ge (1+\delta)\sqrt n$?
Hadamard matrices give exactly $\sqrt n$ in even Sylvester dimensions, and the odd-$k$
Sylvester question is equivalent to the classical asymptotics of Boolean nonlinearity.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open** (11 and 12). Exact small cases computed at creation and independently re-run: max
disc over $\pm1$ $n\times n$ matrices is $2,1,2,3,4$ for $n = 2..6$; an explicit $6\times6$
matrix has ratio $4/\sqrt6 \approx 1.633 > \sqrt2$. Neighbor Conjecture 13 (Sylvester $H_k$,
odd $k$: disc $= \sqrt2\sqrt{2^k}$) is **refuted** for every odd $k \ge 9$ through the
identity $\mathrm{disc}(H_k) = 2^k - 2\rho(\mathrm{RM}(1,k))$ and known nonlinearity records
(Kavut–Yücel [arXiv:0808.0684](https://arxiv.org/abs/0808.0684) at $k = 9$; Patterson–Wiedemann
1983 at $k = 15$); the Updates note explicitly leaves the $H_k$ family available for
Conjecture 12 — whether $\mathrm{disc}(H_k)/\sqrt{2^k}$ stays bounded away from 1 along odd
$k$ is the open asymptotic nonlinearity question. Komlós (Problem 10): $K \ge 1+\sqrt2$
(Kunisky, [arXiv:2111.02974](https://arxiv.org/abs/2111.02974)); see the Komlós example for
its 2025 upper bound.

## What this runs

`sign_matrix_discrepancy.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with numpy/sympy/python-sat/OR-Tools → three audit-verified
papers → dossier → **driver-created primary claim** + `verdict --set-primary` →
`prove --min-papers 3` → report + lint → `problem verdict` → PDF.

The instance program is exact and cheap: exhaustive sign minima ($2^{n-1}$ integer
matvecs), exhaustive maxima over all sign matrices for $n \le 5$, SAT/CP-guided record
search for $n = 7..10$ (parity makes the targets $5, 6, 7$), Walsh–Hadamard transforms for
the $H_k$ table with the $k = 9$ certificate — every record certified via `proof_submit`.
The constructive track then mines the optima for structure (Hadamard-like? circulant?
tensor behaviour?) toward a family; the refuting direction (ratio $\to 1$) is a theorem
about all sign matrices that no computation supplies.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: certified record tables for small $n$, structured-family discrepancies,
the $H_k$/nonlinearity table with an exact $k = 9$ certificate, and a status sketch keeping
Problem 11 (constant unknown), Conjecture 12 (open) and Conjecture 13 (refuted for
$k \ge 9$, true for $k \le 7$) apart — `COMPUTATIONAL_EVIDENCE`, not a resolution. Records
at finite $n$ never establish a $\limsup$; only a family with a proof does.

## Selected references

- J. Spencer (1985), *Six standard deviations suffice*, Trans. AMS 289.
- N. J. Patterson, D. H. Wiedemann (1983), IEEE Trans. IT 29; S. Kavut, S. Maitra,
  M. D. Yücel (2007), IEEE Trans. IT 53; S. Kavut, M. D. Yücel:
  [arXiv:0808.0684](https://arxiv.org/abs/0808.0684).
- D. Kunisky, *The discrepancy of unsatisfiable matrices and a lower bound for the Komlós
  conjecture constant*: [arXiv:2111.02974](https://arxiv.org/abs/2111.02974).
- Bandeira–Kireeva–Maillard–Rödder, *Randomstrasse101: Open Problems of 2024*:
  [arXiv:2504.20539](https://arxiv.org/abs/2504.20539).
