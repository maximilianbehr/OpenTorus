#!/usr/bin/env bash
# OpenTorus workflow for open problems from
# Dereziński–Nakatsukasa–Rebrova, "Towards Universal Convergence of Backward Error
# in Linear System Solvers" (arXiv:2604.16075).
set -e

# Activate your OpenTorus environment (the venv/conda where you installed it) and ensure `opentorus` is on PATH.

rm -rf .opentorus
rm -f notes.md
opentorus init

opentorus config set model.provider ollama
opentorus config set model.name gpt-oss:120b
opentorus config set model.base_url http://localhost:11435
opentorus config set model.timeout_seconds 600
opentorus config set agent.style autonomous
opentorus config set agent.max_steps inf
opentorus config set permissions.mode trusted

# Numerics for backward-error experiments (synthetic hard instances, MINBERR-NE baselines).
mkdir -p docker
cat > docker/Dockerfile << 'EOF'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy mpmath sympy
WORKDIR /work
EOF
opentorus env prepare python-sci --file docker/Dockerfile

# Curated open problems from Section 7 + the motivating question in the Introduction.
# Quote 'EOF' so LaTeX ($...$, \kappa, etc.) is not expanded by the shell.
cat > notes.md << 'EOF'
# Open problems from arXiv:2604.16075

**Source.** Michał Dereziński, Yuji Nakatsukasa, Elizaveta Rebrova,
*Towards Universal Convergence of Backward Error in Linear System Solvers*
([arXiv:2604.16075](https://arxiv.org/abs/2604.16075)).

For invertible $A \in \mathbb{R}^{n \times n}$ and $b \in \mathbb{R}^n$, the relative
backward error of $x$ is
$$
\mathrm{berr}_{A,b}(x)
= \min_{\tilde{A}} \frac{\|\tilde{A}-A\|_2}{\|A\|_2}
\quad\text{s.t.}\quad \tilde{A}x = b.
$$

**Known (from the paper).**
- PSD $A$: Richardson has $\mathrm{berr}_{A,b}(x_k) \le 1/k$ after $k$ steps (universal).
- PSD $A$: MINBERR attains $O(1/k^2)$ universal backward error.
- General $A$: MINBERR-NE on normal equations has $O(\log(\kappa(A))/k)$ — not strictly universal.
- General $A$: perturbed MINBERR-NE on $\tilde{A} = A + \delta G$ ($G$ Gaussian) attains
  $O(\log(n)/k)$ backward error w.r.t. the original $A$.

---

### Problem — Randomness vs universal backward error (primary)

**Prove or disprove:** For general (non-PSD) linear systems, is *any* source of randomness
(e.g. a dense Gaussian perturbation of $A$) *necessary* to obtain a backward-error
convergence rate that is independent of $\kappa(A)$?

Equivalently: does there exist a **deterministic** Krylov-type method whose iterates satisfy
$\mathrm{berr}_{A,b}(x_k) \le f(k)$ for all invertible $A$ and all $b$, with
$f(k) \to 0$ and $f$ depending neither on $\kappa(A)$ nor on $n$?

If impossible, prove a lower bound (e.g. $\Omega(\log(\kappa(A))/k)$ or worse) for any
deterministic matrix-vector algorithm.
EOF

echo "==> Source paper"
opentorus paper add https://arxiv.org/abs/2604.16075

echo "==> Dossiers from curated notes (Section 7 + intro question)"
opentorus problem new --from-markdown notes.md
opentorus problem list

echo "==> Literature + proof/disproof attempt on Problem 1"
opentorus --verbose prove PROBLEM-0001 --min-papers 10

echo "==> Report"
opentorus problem report PROBLEM-0001
opentorus problem report PROBLEM-0001 --lint
opentorus problem export PROBLEM-0001 --pdf
