#!/usr/bin/env bash
# ============================================================================
# OpenTorus example — Tensor concentration: the type-2 constant of tensors
# Source: "Tensor Concentration Inequalities (Problem 16)", Kevin Lucca,
#         randomstrasse101 (ETH Zürich open-problems blog), 2025.
#         https://randomstrasse101.math.ethz.ch/posts/tensor-concentration/
# Primary paper: Bandeira, Gopi, Jiang, Lucca, Rothvoss (2024), arXiv:2411.10633.
#
# Conjecture 16. For p >= 2, symmetric tensors T_i in (R^d)^{⊗ r}, and iid
# standard Gaussians g_i, does the Gaussian average of the symmetric injective
# l_p norm satisfy  E|| sum_i g_i T_i ||_{I_p}  <=  Õ_{r,p}( d^{1/2 - 1/p} *
# sqrt( sum_i ||T_i||_{I_p}^2 ) ) ?  Known for r=p=2 (Ahlswede-Winter) and for
# p >= 2r (arXiv:2411.10633); OPEN for p < 2r and for general rank r >= 3.
#
# What this script does, end to end:
#   1. reset the local .opentorus workspace and re-initialise it
#   2. configure the model + agent (edit the model.* lines for your setup)
#   3. build the python-sci container for random-tensor / injective-norm sweeps
#   4. register the source paper as a local PAPER-* artifact
#   5. write the problem statement to notes.md and create the dossier
#   6. run `opentorus prove` (literature -> proof draft -> gap-fill)
#   7. build an honesty-linted report and export a PDF
#
# Prerequisites:
#   - `opentorus` on PATH (activate the env where you installed it)
#   - Docker, for the python-sci container
#   - a tool-calling model; this script targets a local Ollama server on :11435
#
# WARNING: step 1 runs `rm -rf .opentorus` in this directory.
# Usage: ./tensor_concentration.sh [PROBLEM-ID]   (defaults to PROBLEM-0001)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-PROBLEM-0001}"

# Activate the env where you installed OpenTorus so `opentorus` is on PATH, e.g.:
#   source ~/GITHUB/OpenTorus/.venv/bin/activate

# --- 1. Fresh workspace -----------------------------------------------------
rm -rf .opentorus
rm -f notes.md
opentorus init

# --- 2. Model & agent configuration -----------------------------------------
# Edit these for your provider/model. Defaults: a local Ollama model on :11435.
# A local OpenAI-compatible server works too (cost then reads "$0 (local)"):
#   opentorus config set model.provider openai
#   opentorus config set model.base_url http://localhost:11435   # add /v1 if your server needs it
opentorus config set model.provider ollama
opentorus config set model.name gpt-oss:120b            # or: gemma4:31b, gpt-4o-mini, …
opentorus config set model.base_url http://localhost:11435
opentorus config set model.timeout_seconds 1200         # raise for large local models
opentorus config set agent.style autonomous            # fewer prompts; destructive ops still confirmed
opentorus config set agent.max_steps inf               # no overall step cap (Ctrl-C to stop)
opentorus config set agent.prove_gap_fill_max_steps inf  # no separate gap-fill cap …
# … the no-progress backstop still ends a stuck gap-fill (see prove_gap_fill_no_progress_steps).
opentorus config set permissions.mode trusted          # auto-allow low/medium-risk actions

# --- 3. Numerical experiment environment ------------------------------------
# The agent writes and runs random-tensor sweeps in a pinned container: sample
# symmetric Gaussian tensors, compute the injective l_p norm for small (d, r),
# and check the conjectured bound empirically.
mkdir -p docker
cat > docker/Dockerfile << 'DOCKERFILE'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
DOCKERFILE
opentorus env prepare python-sci --file docker/Dockerfile

# --- 4. Source paper --------------------------------------------------------
# Register the primary paper as a local PAPER-* artifact (reports cite only
# local sources). The prove loop gathers further related work itself.
opentorus paper add https://arxiv.org/abs/2411.10633

# --- 5. Problem statement & dossier -----------------------------------------
# Quote 'NOTES' so the shell does not expand the LaTeX math ($...$, \otimes, …).
cat > notes.md << 'NOTES'
# Problem: Tensor concentration — the type-2 constant of tensors (Conjecture 16)

**Source.** Kevin Lucca, *Tensor Concentration Inequalities (Problem 16)*, randomstrasse101
(ETH Zürich open-problems blog), 2025
([post](https://randomstrasse101.math.ethz.ch/posts/tensor-concentration/)). Primary reference:
A. S. Bandeira, S. Gopi, H. Jiang, K. Lucca, T. Rothvoss,
[arXiv:2411.10633](https://arxiv.org/abs/2411.10633) (2024).

**Setup.** Fix a rank $r \ge 2$ and a dimension $d$. For a symmetric tensor
$T \in (\mathbb{R}^d)^{\otimes r}$ and $p \ge 2$, the *symmetric injective $\ell_p$ norm* is
$$
\lVert T\rVert_{\mathcal{I}_p} \;=\; \max_{\lVert x\rVert_p \le 1} \bigl|\langle T, x^{\otimes r}\rangle\bigr|,
$$
where $\lVert x\rVert_p$ is the $\ell_p$ norm on $\mathbb{R}^d$. Let $T_1,\dots,T_n$ be deterministic
symmetric tensors and $g_1,\dots,g_n$ independent standard Gaussians.

**Conjecture 16 (type-2 constant of tensors).** For every $p \ge 2$,
$$
\mathbb{E}\,\Bigl\lVert \sum_{i=1}^n g_i T_i \Bigr\rVert_{\mathcal{I}_p}
\;\le\;
\tilde{O}_{r,p}\!\left( d^{\,\frac{1}{2}-\frac{1}{p}} \, \sqrt{\sum_{i=1}^n \lVert T_i\rVert_{\mathcal{I}_p}^2} \right),
$$
where $\tilde{O}_{r,p}$ hides constants depending on $r,p$ and polylogarithmic factors in $d$ and $n$.

**Known.**
- $r = p = 2$ (matrices): $\mathbb{E}\lVert \sum_i g_i M_i\rVert_{\mathcal{I}_2} \le C\sqrt{\log(d+1)}\,\sqrt{\sum_i \lVert M_i\rVert_{\mathcal{I}_2}^2}$ (Ahlswede–Winter, 2002).
- The conjecture is **settled for $p \ge 2r$** (Bandeira–Gopi–Jiang–Lucca–Rothvoss, arXiv:2411.10633).

**Open.** Prove (or disprove) Conjecture 16 in the regime $p < 2r$, where a volumetric barrier
obstructs the known argument; and extend to general ranks $r \ge 3$. A disproof would exhibit
tensors $T_i$ and an exponent $p < 2r$ for which the Gaussian average exceeds the right-hand side
by more than polylogarithmic factors.

**Numerically explorable.** For small $(d, r)$, sample symmetric Gaussian tensors $T_i$, compute
$\lVert \cdot\rVert_{\mathcal{I}_p}$ (e.g. by projected gradient / power iteration on $\lVert x\rVert_p \le 1$),
and compare the empirical Gaussian average against $d^{1/2-1/p}\sqrt{\sum_i \lVert T_i\rVert_{\mathcal{I}_p}^2}$
across $p$ on both sides of $2r$ to probe the conjectured rate and the $p < 2r$ barrier.
NOTES
# `--structured` maps the single top-level '# ' heading to one dossier (PROBLEM-0001).
opentorus problem new --from-markdown notes.md --structured
opentorus problem list

# --- 6. Attack the problem --------------------------------------------------
# The prove loop reads the dossier + local papers, may write/run experiments via
# exp_run (random-tensor sweeps), and records claims/evidence/attempts. Numerical
# evidence only *supports* a claim; a verified claim requires a verification artifact.
# --min-papers gates proof drafting on gathering at least N local papers first.
opentorus --verbose prove "${TARGET}" --min-papers 5

# --- 7. Honest report + PDF -------------------------------------------------
opentorus problem report "${TARGET}"
opentorus problem report "${TARGET}" --lint            # honesty linter flags overclaiming
opentorus problem export "${TARGET}" --pdf

echo
echo "Done. See .opentorus/problems/${TARGET}/report.md"
