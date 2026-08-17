# Campaign: The Ryser–Brualdi–Stein conjecture

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — both parts, for every $n$; individual squares
> and small-order exhaustions are internal tools. The driver designates the primary claim
> deterministically.

## The problem

Every $n \times n$ Latin square has a partial transversal of size $n-1$ (Brualdi; Stein),
and every Latin square of *odd* order has a full transversal (Ryser 1967). Even orders can
genuinely lack full transversals — the Cayley table of $\mathbb{Z}_{2m}$ has none — which
is exactly why the conjecture splits by parity.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Mixed frontier, reported per statement.** The $n-1$ part is **proved for all
sufficiently large $n$** — parity-free — by Montgomery
([arXiv:2310.19779](https://arxiv.org/abs/2310.19779), 2023; the title's "even n" refers
to which conjecture case this closes). The result is **still an unpublished preprint**
with a nonconstructive threshold; small orders are covered instead by direct
verification (near transversals for all $n \le 11$: Best–Pula–Wanless, JCD 2021). Prior
bounds: $n - O(\log^2 n)$ (Hatami–Shor 2008), $n - O(\log n/\log\log n)$
(Keevash–Pokrovskiy–Sudakov–Yepremyan,
[arXiv:2005.00526](https://arxiv.org/abs/2005.00526), Trans. AMS B 2022). Ryser's
odd-order full-transversal statement is **open**: verified for order $\le 9$
(McKay–McLeod–Wanless 2006; minimum counts $t(3)=t(5)=t(7)=3$, $t(9)=68$); the 2024 BCC
survey ([arXiv:2406.19873](https://arxiv.org/abs/2406.19873)) expects large odd $n$ to
need new ideas. Group Cayley tables are fully characterized (Hall–Paige, proved 2009):
full transversal iff Sylow 2-subgroups trivial or non-cyclic. Attribution note: Ryser
conjectured only the odd/full statement — the "parity count" version is a misattribution
(Best–Wanless, arXiv:1801.02893) and is false for odd orders.

## What this runs

`ryser_brualdi_stein.sh` follows the campaign template: fresh workspace → config
(timeout 2400s) → container with CP-SAT/python-sat/sympy → three audit-verified papers →
dossier → **driver-created primary claim** + `verdict --set-primary` →
`prove --min-papers 5` → report + lint → `problem verdict` → PDF.

Dual track: the refutation side hunts (a) an odd-order square with no full transversal
(order $\ge 11$; for a fixed square nonexistence is a finite exact-cover check — fully
certifiable) among low-transversal-count structures, and (b) any square with no
$(n-1)$-transversal in the small-order window Montgomery's threshold leaves open. The
proof track certifies Cayley-table facts (odd $\mathbb{Z}_n$ transversals;
$\mathbb{Z}_{2m}$ nonexistence; Hall–Paige on all groups of order $\le 16$) via
`proof_submit` and mines transversal-count statistics.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact small-order certificates, Cayley-table theorems reproduced as
machine checks, a status sketch that keeps four layers apart — the published bounds, the
unpublished large-$n$ theorem, the open odd-order statement, and the group-case
characterization — `COMPUTATIONAL_EVIDENCE`, not a resolution. A run that reports
"Brualdi–Stein is proved" without the large-$n$/preprint qualifiers fails the epistemic
bar; so does one that calls Ryser's odd case settled.

## Selected references

- H. J. Ryser (1967), *Neuere Probleme der Kombinatorik*, Oberwolfach; S. K. Stein
  (1975), Pacific J. Math. 59.
- B. D. McKay, J. C. McLeod, I. M. Wanless (2006), *The number of transversals in a
  Latin square*, Des. Codes Cryptogr. 40.
- P. Keevash, A. Pokrovskiy, B. Sudakov, L. Yepremyan:
  [arXiv:2005.00526](https://arxiv.org/abs/2005.00526) (Trans. AMS B 2022).
- R. Montgomery, *A proof of the Ryser–Brualdi–Stein conjecture for large even n*:
  [arXiv:2310.19779](https://arxiv.org/abs/2310.19779); survey
  [arXiv:2406.19873](https://arxiv.org/abs/2406.19873).
- Hall–Paige: S. Wilcox (2009), A. Evans (2009), J. Bray et al., J. Algebra 545 (2020).
