#!/bin/bash
set -e
# Activate your OpenTorus environment (the venv/conda where you installed it) and ensure `opentorus` is on PATH.

# init
rm -rf .opentorus
opentorus init

# opentorus config
opentorus config set model.provider ollama
opentorus config set model.name gpt-oss:120b
opentorus config set model.base_url http://localhost:11435
opentorus config set model.timeout_seconds 600
opentorus config set agent.style autonomous
opentorus config set agent.max_steps 100
opentorus config set permissions.mode trusted

# Scientific Python (numpy) — user-supplied Dockerfile only.
mkdir -p docker
cat > docker/Dockerfile << 'EOF'
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy mpmath sympy
WORKDIR /work
EOF
opentorus env prepare python-sci --file docker/Dockerfile

# the problem description
# NOTE: quote the heredoc delimiter ('EOF') so the shell does NOT expand the
# LaTeX math (\(L\), $\gamma$, ...) and corrupt the problem statement.
cat > notes.md << 'EOF'
Inverses of Laplacians and related matrices

A new (and likely important) motivation for column subset selection comes from a problem of Markov chain compression.
In this problem, to summarize and simplify, one is presented with a large graph Laplacian \(L\),
and one wants to compute a reduced model in an interpolative fashion,
yielding a small graph Laplacian which approximates the original one well.
In order to guarantee accuracy with respect to the long-timescale dynamics of the respective random walk,
it suffices to bound the accuracy of the Nyström approximation in spectral or nuclear norm:

\[
\left\| K - K_{:, \mathcal{I}} K_{\mathcal{I}, \mathcal{I}}^{-1} K_{\mathcal{I}, :} \right\|_{\{2,*\}}
\]

with respect to a chosen subset \(\mathcal{I}\), while taking

\[
K = (L + \gamma I)^{-1}
\]

with \(\gamma > 0\).
Strictly, takes this objective in the limit \(\gamma \to 0^+\).
We will focus on the nuclear error for simplicity and ease of derivation.
Note that the nuclear Nyström error in may be exactly equated to the CX Frobenius error in by taking

\[
A = K^{1/2},
\]

for instance.

In it is proved that the nuclear Nyström error for inverse Laplacians,
taking care of null space issues,
is a submodular function in \(\mathcal{I}\) if one excludes the empty set from consideration.
Roughly speaking,
this implies that the worst-case nuclear approximation error obtained by choosing \(k\) columns
greedily is bounded to the one obtained by choosing \(s\) columns optimally by a factor decaying like

\[
e^{-k/s}
\]

where \(k \geq s\).
This question may be extended beyond Laplacians to consider positive-definite matrices that are either symmetric diagonally dominant (SDD) matrices or SDD M-matrices (SDDM).

### Problem

**Prove or disprove the submodularity of the nuclear Nyström error when \(L\) is assumed, in contrast to the above, to be**

1. **SDDM and positive-definite**, or
2. **SDD and positive-definite**.

EOF

# create a problem
opentorus problem new --from-markdown notes.md

# try to prove or disprove
opentorus --verbose prove PROBLEM-0001 --disprove

# report bauen, pruefen und pdf
opentorus problem report PROBLEM-0001
opentorus problem report PROBLEM-0001 --lint
opentorus problem export PROBLEM-0001 --pdf
