# The Matrix Spencer conjecture

## Open problem

Does a universal constant $C$ exist such that for all symmetric
$A_1,\dots,A_n \in \mathbb{R}^{n\times n}$ with $\lVert A_i\rVert \le 1$ there are signs
$\varepsilon_i \in \{\pm 1\}$ with $\lVert \sum_i \varepsilon_i A_i \rVert \le C\sqrt{n}$?
This is the matrix analogue of Spencer's six-standard-deviations theorem. Random signs lose
a $\sqrt{\log n}$ factor; the conjecture asks chosen signs to remove it.

Status (August 2026): **open**. The strongest result proves it whenever every $A_i$ has rank
at most $n/\log^3 n$ ([Bansal–Jiang–Meka, STOC 2023, arXiv:2208.11286](https://arxiv.org/abs/2208.11286));
the general case appears in the
[Randomstrasse101 open-problems collection (arXiv:2504.20539)](https://arxiv.org/abs/2504.20539).

## What this runs

`matrix_spencer.sh` follows the standard example workflow (fresh workspace → config →
`python-sci` container → two source papers → dossier → `opentorus prove --min-papers 5` →
honesty-linted report + PDF). The agent can run sign-discrepancy sweeps as `EXP-*`
experiments: exhaustive sign minima for small $n$, SDP relaxations, and adversarial
instance searches. A candidate refutation is a finite certificate (fixed matrices +
exhaustively verified sign minimum) that can be re-checked in exact arithmetic.

## Prerequisites

- **Docker**; **a tool-calling model** (defaults: local Ollama on 11434, override with
  `OPENTORUS_MODEL` / `OPENTORUS_BASE_URL`). The script resets `.opentorus/`.

## Run

```bash
bash matrix_spencer.sh
```

## Honesty note

Matrix Spencer resisted a decade of matrix-concentration technology; the expected honest
outcome is a literature-grounded status sketch plus reproducible small-$n$ experiments.
Empirical $O(\sqrt n)$ behaviour on random instances is *support*, never proof — the report
linter enforces the distinction, and a claimed counterexample must survive exact
re-verification before the counterexample-verified status is reachable.

## Selected references

- N. Bansal, H. Jiang, R. Meka (2023), STOC. [arXiv:2208.11286](https://arxiv.org/abs/2208.11286)
- A. S. Bandeira et al. (2025), *Randomstrasse101: Open Problems of 2024*.
  [arXiv:2504.20539](https://arxiv.org/abs/2504.20539)
- J. Spencer (1985), *Six standard deviations suffice*, Trans. AMS 289.
