#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=11
python3 scripts/convention_check_laplacian.py
