# Tensor concentration: the type-2 constant of tensors

## Open problem

For a symmetric tensor $T \in (\mathbb{R}^d)^{\otimes r}$ and $p \ge 2$, the symmetric injective
$\ell_p$ norm is $\lVert T\rVert_{\mathcal{I}_p} = \max_{\lVert x\rVert_p \le 1} |\langle T, x^{\otimes r}\rangle|$.
Given deterministic symmetric tensors $T_1,\dots,T_n$ and independent standard Gaussians
$g_1,\dots,g_n$, **Conjecture 16** asks whether, for every $p \ge 2$,

$$
\mathbb{E}\,\Bigl\lVert \sum_{i=1}^n g_i T_i \Bigr\rVert_{\mathcal{I}_p}
\;\le\;
\tilde{O}_{r,p}\!\left( d^{\,\frac12-\frac1p} \, \sqrt{\textstyle\sum_{i=1}^n \lVert T_i\rVert_{\mathcal{I}_p}^2} \right),
$$

with $\tilde{O}_{r,p}$ hiding $r,p$-constants and polylog factors in $d,n$. The bound is classical
for matrices ($r=p=2$, Ahlswede–Winter 2002) and is **settled for $p \ge 2r$**
(Bandeira, Gopi, Jiang, Lucca, Rothvoss, [arXiv:2411.10633](https://arxiv.org/abs/2411.10633)). It
is **open for $p < 2r$** — where a volumetric barrier blocks the known argument — and for general
ranks $r \ge 3$.

This example is built from the open-problem post *Tensor Concentration Inequalities (Problem 16)*
by Kevin Lucca on the [randomstrasse101](https://randomstrasse101.math.ethz.ch/posts/tensor-concentration/)
ETH Zürich blog.

## What this runs

The driver `tensor_concentration.sh` runs an end-to-end OpenTorus workflow:

1. **Init** — `rm -rf .opentorus`, then `opentorus init` (a fresh workspace).
2. **Configure** — model provider/name/base URL/timeout, `agent.style autonomous`,
   `agent.max_steps inf`, `agent.prove_gap_fill_max_steps inf`, `permissions.mode trusted`.
   The gap-fill no-progress backstop still ends a stuck run even with the caps at `inf`.
3. **Prepare environment** — write `docker/Dockerfile` (numpy, scipy, mpmath, sympy) and
   register the `python-sci` container via `opentorus env prepare`.
4. **Add the source paper** — `opentorus paper add https://arxiv.org/abs/2411.10633`.
5. **Create the dossier** — `opentorus problem new --from-markdown notes.md --structured`
   (the statement is written inline by the script via a heredoc).
6. **Prove** — `opentorus prove PROBLEM-0001 --min-papers 5` (literature → proof draft →
   gap-fill); the agent may write random-tensor / injective-norm sweeps as `EXP-*` experiments.
7. **Report and export** — `opentorus problem report --lint` and `opentorus problem export --pdf`.

## Prerequisites

- **Docker** — to build and run the `python-sci` container for the numerical sweeps.
- **A tool-calling model** — the script targets a local Ollama model on port 11435
  (`gpt-oss:120b`); set `model.provider`, `model.name`, and `model.base_url` for your own
  setup. A local OpenAI-compatible server also works (cost then reads `$0 (local)`).
  OpenTorus refuses or warns up front if the configured model cannot call tools.
- The script **resets the local workspace** (`rm -rf .opentorus`).

## Run

```bash
bash tensor_concentration.sh
```

## Honesty note

This is a hard open conjecture in high-dimensional probability and functional analysis; a small
local model is not expected to prove it. The value here is the auditable workflow: numerical
experiments and proof sketches only *support* a claim — only a verification artifact verifies one.
The generated report is checked by the artifact-aware honesty linter, which flags overclaiming and
never upgrades evidence into proof; a run that gathers evidence but cannot close every `[GAP-n]`
ends with an honest, gapped sketch (status `HEURISTIC_ONLY` / `EXPERIMENTAL_ONLY`).

## Selected references (from the post)

- A. S. Bandeira, S. Gopi, H. Jiang, K. Lucca, T. Rothvoss (2024), [arXiv:2411.10633](https://arxiv.org/abs/2411.10633) — settles $p \ge 2r$.
- R. Ahlswede, A. Winter (2002), *IEEE Trans. Inform. Theory* 48(3), 569–579 — the matrix case.
- A. S. Bandeira, M. Boedihardjo, R. van Handel (2023), *Invent. Math.* 234, 419–487 — matrix concentration without logs.
- R. Latała (2006), *Ann. Probab.* 34(6), 2315–2331 — Gaussian chaos / tensor norms.
