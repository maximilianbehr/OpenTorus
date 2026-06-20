#!/usr/bin/env bash
# Literature + citation-honest dossier report for the Polynomial Hirsch Conjecture.
set -euo pipefail
cd "$(dirname "$0")"
# Activate your OpenTorus environment (the venv/conda where you installed it) and ensure `opentorus` is on PATH.

rm -rf .opentorus
opentorus init
opentorus config set model.provider ollama
opentorus config set model.name gpt-oss:120b
opentorus config set model.base_url http://localhost:11435
opentorus config set model.timeout_seconds 600
opentorus config set agent.style autonomous
opentorus config set permissions.mode trusted
opentorus config set agent.max_steps 100

HIRSCH_STMT='Does there exist a polynomial p(n,d) bounding the graph diameter of every d-dimensional polytope with n facets? (Polynomial Hirsch Conjecture)'
opentorus problem new "$HIRSCH_STMT" \
  --title "Polynomial Hirsch Conjecture" \
  --domain "polyhedral combinatorics / linear programming" \
  --tag hirsch --tag polytope-diameter

opentorus problem show PROBLEM-0001
opentorus --verbose prove PROBLEM-0001 --min-papers 10

echo "==> Building dossier report…"
opentorus problem report PROBLEM-0001
opentorus problem export PROBLEM-0001 --pdf
