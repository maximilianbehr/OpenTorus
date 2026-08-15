# Calibration: Sendov's conjecture

> **Calibration example** — known ground truth; regression-tests literature freshness and
> the "formally verified" epistemic category.

## The problem

Sendov's conjecture (1959): if all zeros of a degree-$n \ge 2$ polynomial lie in the closed
unit disk, every zero has a critical point within distance 1. Classically known for
$n \le 8$ (Brown–Xiang) and for all sufficiently large $n$
([Tao, arXiv:2012.04125](https://arxiv.org/abs/2012.04125), Acta Math. 229), with the
intermediate degrees long open.

## Ground truth (August 2026)

**Resolved.** A complete proof for all degrees was announced in August 2026 — AI-assisted
(Lech Mazur) and **verified in Lean** — and digested in
[Terence Tao's blog post of August 12, 2026](https://terrytao.wordpress.com/2026/08/12/a-digestion-of-the-proof-of-sendovs-conjecture/).
This example was originally slated as an open problem and was moved to calibration when the
status check at example-creation time (August 14, 2026) found the resolution — which is
precisely the failure mode this category exists to catch.

## Expected honest outcome

A passing run:

1. finds the August 2026 resolution during the literature phase and reports the conjecture
   as **solved**, correctly noting the Lean formal verification — a stronger epistemic
   category than a bare preprint, and the report should say so;
2. does not present the problem as open (that fails calibration on freshness);
3. still distinguishes what is peer-reviewed from what is announced;
4. records interval-certified spot checks of the Sendov distance for sampled polynomials as
   support-only `EXP-*` evidence.

## Run

```bash
bash sendov.sh
```

Prerequisites as usual (Docker; tool-calling model; resets `.opentorus/`).

## References

- Bl. Sendov (1959), via Hayman's *Research Problems in Function Theory*.
- J. E. Brown, G. Xiang (1999), *Proof of the Sendov conjecture for polynomials of degree
  at most eight*, J. Math. Anal. Appl. 232.
- T. Tao (2022), *Sendov's conjecture for sufficiently-high-degree polynomials*, Acta Math.
  229. [arXiv:2012.04125](https://arxiv.org/abs/2012.04125)
- T. Tao, blog (2026-08-12): *A digestion of the proof of Sendov's conjecture*.
