"""The frozen formal benchmark: small, self-written Lean 4 + Mathlib statements.

Every statement here was written for OpenTorus (no third-party benchmark text is
copied) and is a standard, true fact stated as simply as possible, so that a failure
measures the prover, not a mis-stated problem. Each entry is a complete frozen file:
``import Mathlib``, optional definitions, exactly one theorem whose proof is ``sorry``
— the same shape as a ``FSTMT-*`` frozen statement, checked by the same gate.

The split is fixed: ``dev`` items may be used to develop prompts and as worked
examples; ``heldout`` items are only ever shown to a prover one at a time, as the
problem to solve, and never as examples. :data:`MANIFEST_SHA256` pins the data — a
change to any statement or to the split is a new benchmark version, not an edit.
"""

from __future__ import annotations

from typing import Literal

Split = Literal["dev", "heldout"]

_H = "import Mathlib\n\n"

# (id, split, informal statement, frozen Lean file)
PROBLEMS: tuple[tuple[str, Split, str, str], ...] = (
    (
        "fb-001",
        "dev",
        "Adding zero to a natural number leaves it unchanged.",
        _H + "theorem fb_add_zero (n : ℕ) : n + 0 = n := by\n  sorry\n",
    ),
    (
        "fb-002",
        "dev",
        "Twice a natural number is the number added to itself.",
        _H + "theorem fb_two_mul (n : ℕ) : 2 * n = n + n := by\n  sorry\n",
    ),
    (
        "fb-003",
        "dev",
        "The square of a real number is nonnegative.",
        _H + "theorem fb_sq_nonneg (x : ℝ) : 0 ≤ x ^ 2 := by\n  sorry\n",
    ),
    (
        "fb-004",
        "dev",
        "The product of two consecutive natural numbers is even.",
        _H + "theorem fb_even_consecutive (n : ℕ) : Even (n * (n + 1)) := by\n  sorry\n",
    ),
    (
        "fb-005",
        "dev",
        "The arithmetic mean of a² and b² bounds ab.",
        _H + "theorem fb_two_mul_le (a b : ℝ) : a * b ≤ (a ^ 2 + b ^ 2) / 2 := by\n  sorry\n",
    ),
    (
        "fb-006",
        "dev",
        "The triangle inequality for the absolute value on ℝ.",
        _H + "theorem fb_abs_add (a b : ℝ) : |a + b| ≤ |a| + |b| := by\n  sorry\n",
    ),
    (
        "fb-007",
        "dev",
        "Two is prime.",
        _H + "theorem fb_prime_two : Nat.Prime 2 := by\n  sorry\n",
    ),
    (
        "fb-008",
        "dev",
        "There are primes above every natural number.",
        _H + "theorem fb_primes_unbounded (n : ℕ) : ∃ p, n ≤ p ∧ Nat.Prime p := by\n  sorry\n",
    ),
    (
        "fb-009",
        "dev",
        "The square of an odd integer is odd.",
        _H + "theorem fb_odd_sq (n : ℤ) (h : Odd n) : Odd (n ^ 2) := by\n  sorry\n",
    ),
    (
        "fb-010",
        "dev",
        "A factorial is positive.",
        _H + "theorem fb_factorial_pos (n : ℕ) : 0 < n.factorial := by\n  sorry\n",
    ),
    (
        "fb-011",
        "dev",
        "The exponential function is positive.",
        _H + "theorem fb_exp_pos (x : ℝ) : 0 < Real.exp x := by\n  sorry\n",
    ),
    (
        "fb-012",
        "dev",
        "Solve the linear equation 3x + 2 = 11.",
        _H + "theorem fb_linear (x : ℝ) (h : 3 * x + 2 = 11) : x = 3 := by\n  sorry\n",
    ),
    (
        "fb-013",
        "dev",
        "The gcd is symmetric.",
        _H + "theorem fb_gcd_comm (a b : ℕ) : Nat.gcd a b = Nat.gcd b a := by\n  sorry\n",
    ),
    (
        "fb-014",
        "dev",
        "Difference of squares over ℤ.",
        _H
        + "theorem fb_sq_sub_sq (a b : ℤ) : a ^ 2 - b ^ 2 = (a - b) * (a + b) := by\n"
        + "  sorry\n",
    ),
    (
        "fb-015",
        "dev",
        "The sum of the first n odd numbers is n².",
        _H
        + "theorem fb_sum_odd (n : ℕ) : ∑ i ∈ Finset.range n, (2 * i + 1) = n ^ 2 := by\n"
        + "  sorry\n",
    ),
    (
        "fb-016",
        "dev",
        "A recursively doubled sequence starting at 1 is 2ⁿ.",
        _H
        + "def fbSeq : ℕ → ℕ\n  | 0 => 1\n  | n + 1 => 2 * fbSeq n\n\n"
        + "theorem fb_seq_closed (n : ℕ) : fbSeq n = 2 ^ n := by\n  sorry\n",
    ),
    (
        "fb-017",
        "heldout",
        "√2 is irrational.",
        _H + "theorem fb_irrational_sqrt_two : Irrational (Real.sqrt 2) := by\n  sorry\n",
    ),
    (
        "fb-018",
        "heldout",
        "n³ − n is divisible by 6 for every natural number n.",
        _H + "theorem fb_six_dvd (n : ℕ) : 6 ∣ n ^ 3 - n := by\n  sorry\n",
    ),
    (
        "fb-019",
        "heldout",
        "A square of an integer is 0 or 1 modulo 4.",
        _H + "theorem fb_sq_mod_four (n : ℤ) : n ^ 2 % 4 = 0 ∨ n ^ 2 % 4 = 1 := by\n  sorry\n",
    ),
    (
        "fb-020",
        "heldout",
        "The two-term Cauchy–Schwarz inequality.",
        _H
        + "theorem fb_cauchy_two (a b c d : ℝ) :\n"
        + "    (a * c + b * d) ^ 2 ≤ (a ^ 2 + b ^ 2) * (c ^ 2 + d ^ 2) := by\n  sorry\n",
    ),
    (
        "fb-021",
        "heldout",
        "The geometric sum 1 + 2 + … + 2ⁿ⁻¹ equals 2ⁿ − 1.",
        _H
        + "theorem fb_geom_two (n : ℕ) : ∑ i ∈ Finset.range n, 2 ^ i = 2 ^ n - 1 := by\n"
        + "  sorry\n",
    ),
    (
        "fb-022",
        "heldout",
        "Binomial coefficients are symmetric.",
        _H
        + "theorem fb_choose_symm (n k : ℕ) (h : k ≤ n) :\n"
        + "    n.choose k = n.choose (n - k) := by\n  sorry\n",
    ),
    (
        "fb-023",
        "heldout",
        "A finite set with k elements has 2ᵏ subsets.",
        _H
        + "theorem fb_card_powerset (s : Finset ℕ) : s.powerset.card = 2 ^ s.card := by\n"
        + "  sorry\n",
    ),
    (
        "fb-024",
        "heldout",
        "x + 1/x ≥ 2 for positive real x.",
        _H + "theorem fb_add_inv (x : ℝ) (hx : 0 < x) : 2 ≤ x + 1 / x := by\n  sorry\n",
    ),
    (
        "fb-025",
        "heldout",
        "8ⁿ − 1 is divisible by 7.",
        _H + "theorem fb_seven_dvd (n : ℕ) : 7 ∣ 8 ^ n - 1 := by\n  sorry\n",
    ),
    (
        "fb-026",
        "heldout",
        "Gauss: twice the sum 0 + 1 + … + n is n(n + 1).",
        _H
        + "theorem fb_gauss (n : ℕ) : 2 * ∑ i ∈ Finset.range (n + 1), i = n * (n + 1) := by\n"
        + "  sorry\n",
    ),
)

# sha256 over "id|split|lean\n" for every entry in order (see ``manifest_sha256``).
MANIFEST_SHA256 = "3b60f097043a52a82cca1f7230790a2dd47502fa5a29d405154865016f7bc3ac"
