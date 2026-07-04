#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=7
python3 scripts/check_nystrom_submodularity.py --cls sddm --n 6 --trials 15 --pairs 6 --seed 7
