"""Reproducible agent evaluation harness.

Evals apply OpenTorus's own research discipline to its development: each run is
reproducible (fixed seed, captured environment) and produces a manifest under
``.opentorus/evals/``. Results are *evidence* about behavior on a given suite,
never an auto-promoted claim that "the agent is good".
"""

from opentorus.evals.harness import EvalCase, EvalResult, EvalRun, run_suite
from opentorus.evals.suites import SUITES, get_suite

__all__ = ["SUITES", "EvalCase", "EvalResult", "EvalRun", "get_suite", "run_suite"]
