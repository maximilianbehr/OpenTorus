# Campaign: Lovett's hypercube set system (random neighbourhood subsets)

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is an asymptotic statement for every $n$ — discrepancy $\Theta(\sqrt n)$ with
> no polylog factor; exact small-$n$ discrepancies are internal tools. The driver
> designates the primary claim deterministically.
>
> Source: [AIM Problem List *Hereditary discrepancy and factorization norms*](http://aimpl.org/hereddiscrep/1/)
> (ed. S. Garg, AIM workshop Feb–Mar 2016, org. Nikolov–Talwar; http only), Problem 1.25
> [Shachar Lovett].

## The problem

Elements are the $2^n$ vertices of the hypercube; each vertex $v$ owns a set $S_v$ that is
a random subset of its $n$ neighbours. What is the discrepancy? With the *full*
neighbourhoods a parity colouring gives discrepancy $\le 1$; the random sparsification
destroys that, and the system sits precisely at the "logarithmic sparsity" boundary
($k = n = \log_2 N$) where the Beck–Fiala conjecture is still open.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open** — no paper treats the system. Bracket at audit time: $\tilde O(\sqrt n)$ from
Bansal–Jiang's 2025 Beck–Fiala bound ([arXiv:2508.03961](https://arxiv.org/abs/2508.03961),
$\mathrm{poly}(\log\log N)$ loss); $\Omega(\sqrt n)$ w.h.p. from a first-moment +
Littlewood–Offord argument derived at creation and independently re-checked (not in the
literature; disc $\ge 2$ for $n \ge 23$, $\ge 3$ for $n \ge 64$). Altschuler–Tikhomirov's
2026 result stops just above this regime. Random-hypergraph theorems (Ezra–Lovett,
Bansal–Meka, Potukuchi, MacRury et al.) do not apply verbatim. Creation-time exact SAT
values, done twice independently: discrepancy $1$ or $2$ for $n \le 8$, skewing to $2$ at
$n = 9$.

## What this runs

`hypercube_random_neighbourhoods.sh` follows the campaign template: fresh workspace →
config (timeout 2400s) → container with python-sat + numpy → five audit-verified papers
→ dossier → **driver-created primary claim** + `verdict --set-primary` →
`campaign start --mode prove-or-refute` (a budgeted branch portfolio: proof, counterexample, literature, formalization, ...; `campaign status`/`tree`/`verify` afterwards) → report + lint → `problem verdict` → PDF.

The instance program: exact SAT discrepancies for sampled systems ($n \le 9$–$10$),
heuristic colourings to $n \approx 16$, and — first of all — a machine-checked
`proof_submit` of the lower-bound lemma (atom bound + union bound), which is the one
piece of the bracket that is not a citation. Removing the polylog from the upper bound by
using the cube structure (Fourier basis, direction-wise decoupling) is the proof route; a
drift of $\mathrm{disc}/\sqrt n$ would be the refutation signal.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: a verified lower-bound lemma, exact small-$n$ data, and a status
sketch that keeps the cited $\tilde O(\sqrt n)$ apart from the conjectured $\Theta(\sqrt n)$
— `COMPUTATIONAL_EVIDENCE` plus at most a machine-checked lemma, not a resolution. Do
not call the system a Beck–Fiala or random-hypergraph corollary; do not state $p = 1/2$
as given.

## Selected references

- N. Bansal, H. Jiang, *Decoupling via affine spectral-independence: Beck–Fiala and
  Komlós bounds beyond Banaszczyk*: [arXiv:2508.03961](https://arxiv.org/abs/2508.03961);
  *An improved bound for the Beck–Fiala conjecture*:
  [arXiv:2508.01937](https://arxiv.org/abs/2508.01937).
- E. Ezra, S. Lovett, *On the Beck–Fiala conjecture for random set systems*:
  [arXiv:1511.00583](https://arxiv.org/abs/1511.00583).
- C. MacRury, T. Masařík, L. Pai, X. Pérez-Giménez, *The phase transition of discrepancy
  in random hypergraphs*: [arXiv:2102.07342](https://arxiv.org/abs/2102.07342).
- A. Potukuchi, *A spectral bound on hypergraph discrepancy*:
  [arXiv:1907.04117](https://arxiv.org/abs/1907.04117).
- N. Bansal, A. Nikolov, *Discrepancy theory* (monograph): arXiv:2608.00140.
