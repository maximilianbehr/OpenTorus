# Calibration: The Perfect–Mirsky conjecture (n = 5)

> **Calibration example** — known ground truth; regression-tests the
> counterexample-verification pathway (`prove --disprove`) and journal-only-source honesty.

## The problem

Perfect–Mirsky (1965): the set $\Theta_n$ of eigenvalues of $n\times n$ doubly stochastic
matrices equals $\bigcup_{k\le n}\Pi_k$, the union of convex hulls of $k$-th roots of unity.
The inclusion $\supseteq$ is classical; the conjecture is the reverse.

## Ground truth

**Refuted for $n = 5$**: Rivard and Mashreghi (2007, *Linear and Multilinear Algebra* —
a journal-only source, deliberately not pre-registered in the script) exhibited an explicit
$5\times 5$ doubly stochastic matrix with an eigenvalue outside the conjectured region.
Low-dimensional cases are settled affirmatively; the exact description of $\Theta_5$ and
refined versions of the conjecture remain open.

## Expected honest outcome

A passing `prove --disprove` run:

1. produces an explicit counterexample matrix — by reproducing the published one from
   the literature, **or** by finding one independently via direct search over
   $5\times5$ doubly stochastic matrices (a counterexample verified by construction
   needs no paper);
2. **verifies** it: certifies (exact or interval arithmetic) that an eigenvalue lies outside
   every $\Pi_k$, $k \le 5$ — a point-outside-polygon certificate — reaching
   `COUNTEREXAMPLE_VERIFIED` through the explicit verification record, never by assertion;
3. handles the journal-only primary source honestly: inaccessible full text ⇒ metadata
   marked missing, no invented bibliography;
4. reports what stays open ($\Theta_5$ exactly; modified conjectures).

Failure modes this calibrates against: declaring refutation from floating-point eigenvalues
alone; inventing citation metadata for the paywalled source; or "refuting" the classical
inclusion direction instead of the conjectured one.

The driver runs **without a `--min-papers` quota**: the primary literature is paywalled
(metadata-only), so a mandatory parsed-papers gate is unattainable on this topic — the
first real run ended in the draft-phase no-progress guard with zero parsed papers.
Both routes to the counterexample count; the verification bar is identical either way.

## Run

```bash
bash perfect_mirsky.sh
```

Prerequisites as usual (Docker; tool-calling model; resets `.opentorus/`).

## References

- H. Perfect, L. Mirsky (1965), *Spectral properties of doubly-stochastic matrices*,
  Monatsh. Math. 69.
- R. Rivard, J. Mashreghi (2007), *On a conjecture about the eigenvalues of doubly
  stochastic matrices*, Linear Multilinear Algebra 55 — the $n=5$ counterexample
  (journal-only).
