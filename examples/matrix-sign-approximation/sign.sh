#!/bin/bash

set -e

# Activate your OpenTorus environment (the venv/conda where you installed it) and ensure `opentorus` is on PATH.

# init
rm -rf .opentorus
rm notes.md
opentorus init

# opentorus config
opentorus config set model.provider ollama
opentorus config set model.name gpt-oss:120b
opentorus config set model.name qwen3.6:35b
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
# LaTeX math ($$, $m$, $\delta$, ...). An unquoted << EOF turns $$ into the
# shell PID and drops $m$/$\delta$, corrupting the problem statement.
cat > notes.md << 'EOF'
Let $\Pi_{2^m}^*$ be the set of univariate polynomials whose corresponding matrix function
can be computed with $m$ matrix-matrix multiplications and an arbitrary number of matrix
additions and scalings. We consider the problem of determining the best such polynomial
that approximates the sign function in

$$
I := [-1,-\delta] \cup [\delta,1],
$$

$$
\varepsilon_m^* =
\min_{p \in \Pi_{2^m}^*}
\max_{x \in I}
|p(x) - \operatorname{sign}(x)|.
$$

What is the asymptotic error $\varepsilon_m^*$ as a function of $m$ and $\delta$?
EOF

# create a problem
opentorus problem new --from-markdown notes.md
opentorus problem show PROBLEM-0001

# add relevant paper
opentorus paper add https://arxiv.org/abs/2504.01500

# lit search, planning, and prove
opentorus --verbose prove PROBLEM-0001 --min-papers 10

# report bauen, pruefen und pdf
opentorus problem report PROBLEM-0001
opentorus problem report PROBLEM-0001 --lint
opentorus problem export PROBLEM-0001 --pdf
