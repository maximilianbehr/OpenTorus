# Calibration: Formal verification of fast matrix multiplication (Coq/Lean)

> **Calibration example** — known ground truth; exercises the **formal-backend
> round-trip** (write → compile → error feedback → fix → resubmit) end to end.

## The task

Strassen's 7-product scheme for $2\times2$ matrix multiplication (1969) and Laderman's
23-product scheme for $3\times3$ (1976) are correct — that is not in question. Their
correctness is a finite system of polynomial identities over a commutative ring, and each
identity is closed mechanically by the `ring` tactic in Coq or Lean 4 (Mathlib). What this
example tests is the **loop**: the agent must produce compiling formal source, read the
checker's error output through `proof_submit`, repair the source, and resubmit until
ACCEPTED. This is the first example whose verification artifacts come from a proof
assistant rather than sympy/interval/SMT.

## Backend selection

The script picks, in order:

1. **host `coqc`** — used directly;
2. **host `lake` with `LEAN_PROJECT`** pointing to a Mathlib-enabled Lean project —
   `lean_command` becomes `lake --dir $LEAN_PROJECT env lean`;
3. **Docker fallback** — containerized Coq via `coqorg/coq:8.20`, with `/tmp` (and
   `$TMPDIR`) mounted so the verifier's temp file is visible in the container. Verified
   working: `docker run --rm -v /tmp:/tmp coqorg/coq:8.20 coqc <file>` accepts a `ring`
   proof out of the box.

## Expected honest outcome

A passing run:

1. produces at least one **ACCEPTED** `proof_submit` (backend `coq` or `lean4`) covering
   the four Strassen identities — a `PROOF-*` artifact with a `validates` edge to the
   claim;
2. preserves every rejected attempt (compiler errors) as first-class artifacts — the
   error-feedback iterations are the point, not a blemish;
3. keeps the numeric random-matrix check as support-only `EXP-*` evidence, clearly below
   the formal artifact in the report;
4. still does not set the claim to `formally_verified` by itself — the gated status
   update remains the only promotion path;
5. stretch: per-entry Laderman lemmas (nine identities from the parsed rank-23 scheme
   papers), reported honestly as "machine-checked for entries X, not yet for Y" if
   incomplete.

## Run

```bash
bash strassen_formal.sh
```

Prerequisites: Docker (for the numeric container, and for the Coq fallback if no host
prover is installed); a tool-calling model (defaults: local Ollama on 11434; override
`OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`). Resets `.opentorus/`.

## References

- V. Strassen (1969), *Gaussian elimination is not optimal*, Numer. Math. 13.
- J. B. Laderman (1976), *A noncommutative algorithm for multiplying 3×3 matrices using
  23 multiplications*, Bull. AMS 82.
- Explicit rank-23 schemes: [arXiv:2604.27645](https://arxiv.org/abs/2604.27645),
  [arXiv:2601.05272](https://arxiv.org/abs/2601.05272)
