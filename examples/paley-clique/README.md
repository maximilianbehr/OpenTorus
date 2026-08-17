# Campaign: The clique number of Paley graphs

> **Campaign dossier** (see [CAMPAIGN_TEMPLATE.md](../CAMPAIGN_TEMPLATE.md)): the primary
> target is the full quantified conjecture — polylog clique number for every prime
> $p \equiv 1 \ (4)$; per-prime computations and the localization relaxations are
> internal tools. The driver designates the primary claim deterministically.
>
> Source: [Randomstrasse101](https://randomstrasse101.math.ethz.ch/posts/PaleyGraph/)
> (ETH Zürich open-problems blog), Conjectures 25–29; archived as
> [arXiv:2603.29571](https://arxiv.org/abs/2603.29571).

## The problem

The Paley graph $G_p$ ($i \sim j$ iff $i-j$ is a quadratic residue mod $p$) is the model
pseudorandom graph, and pseudorandom graphs of density $1/2$ "should" have clique number
$O(\log p)$. Conjecture: $\omega(G_p) = O(\mathrm{polylog}\,p)$. Every proof technique
stalls at $\sqrt p$ — the same square-root barrier that blocks deterministic RIP matrices,
to which the problem is formally tied.

## Status audit (2026-08-17, fresh web check, independently counter-checked)

**Open.** Upper bounds: $\vartheta(\overline{G_p}) = \sqrt p$ exactly; the only improvement
is Hanson–Petridis $\sqrt{p/2}+1$ ([arXiv:1905.09134](https://arxiv.org/abs/1905.09134),
Proc. LMS 2021). Lower bounds are only logarithmic — $(\tfrac12+o(1))\log_2 p$ for all $p$
(Ramsey/Cohen), $c\log p\log\log\log p$ infinitely often (Graham–Ringrose 1990). The blog's
localization program
(Kunisky, [arXiv:2303.16475](https://arxiv.org/abs/2303.16475)): the 1-localization is
circulant, so its $\vartheta$ is an LP conjectured $\sim\sqrt{p/2}$ (Magsino–Mixon–Parshall,
[arXiv:1907.05971](https://arxiv.org/abs/1907.05971)); the 2-localization is conjectured to
give $\tfrac23\sqrt p$; degree-4 SoS is conjectured to give $O(p^{1/2-\epsilon})$ but is
provably no better than $\Omega(p^{1/3})$ (Kunisky–Yu,
[arXiv:2211.02713](https://arxiv.org/abs/2211.02713)); the Paley-ETF RIP conjecture is
tied to it in both directions, neither unconditional. No 2025–2026 improvement for prime
$p$.

## What this runs

`paley_clique.sh` follows the campaign template: fresh workspace → config (timeout
2400s) → container with networkx/python-sat/scipy/cvxpy → four audit-verified papers →
dossier → **driver-created primary claim** + `verdict --set-primary` →
`prove --min-papers 5` → report + lint → `problem verdict` → PDF.

The instance program is where a run can produce genuinely new certified facts: exact
$\omega(G_p)$ for small primes; the 1-localization LP with an exact rational dual, giving
certified per-$p$ bounds $\lfloor\vartheta\rfloor+1$; the 2-localization SDP, where any $p$
with $\lfloor\vartheta(\overline{G_{p,2}})\rfloor + 2 < \lfloor\sqrt{p/2}\rfloor + 1$ is a
certified improvement of Hanson–Petridis at that $p$; degree-4 SoS exponent fits under
symmetry reduction. The polylog statement itself is asymptotic — no computation proves it,
and only a certified family would refute it.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults to local Ollama on :11434; override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`).
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Honesty note

Realistic outcomes: exact clique tables, certified localization bounds per prime (possibly
beating $\sqrt{p/2}+1$ at specific $p$ — a `VERIFIED_PARTIAL_THEOREM`-grade artifact for
that $p$), SoS exponent evidence, and a literature layer that keeps the theorem
($\sqrt{p/2}+1$), the limitation ($\Omega(p^{1/3})$ for degree 4), and the four auxiliary
conjectures apart — `COMPUTATIONAL_EVIDENCE`, not a resolution.

## Selected references

- R. Paley (1933); S. D. Cohen (1988), *Clique numbers of Paley graphs*, Quaestiones Math.
  11; S. W. Graham, C. J. Ringrose (1990), *Lower bounds for least quadratic non-residues*
  (infinitely-often lower bounds).
- B. Hanson, G. Petridis, *Refined estimates concerning sumsets contained in the roots of
  unity*: [arXiv:1905.09134](https://arxiv.org/abs/1905.09134) (Proc. LMS 2021).
- D. Kunisky, *Spectral pseudorandomness and the road to improved clique number bounds for
  Paley graphs*: [arXiv:2303.16475](https://arxiv.org/abs/2303.16475) (Exp. Math. 2024).
- D. Kunisky, X. Yu, *A degree 4 sum-of-squares lower bound for the clique number of the
  Paley graph*: [arXiv:2211.02713](https://arxiv.org/abs/2211.02713) (CCC 2023).
- M. Magsino, D. G. Mixon, H. Parshall, *Linear programming bounds for cliques in Paley
  graphs*: [arXiv:1907.05971](https://arxiv.org/abs/1907.05971).
- Bandeira–Fickus–Mixon–Wong, arXiv:1202.1234; Bandeira–Mixon–Moreira, arXiv:1410.6457;
  Satake, arXiv:2011.02907 (Paley ETF / RIP).
