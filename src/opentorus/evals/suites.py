"""Built-in eval suites.

The ``smoke`` suite exercises the core loop deterministically against the mock
provider: tool selection, the observed-vs-validated framing, and the honest
fallback when no tool applies. Suites are intentionally small and reproducible.
"""

from __future__ import annotations

from opentorus.errors import OpenTorusError
from opentorus.evals.harness import EvalCase

SUITES: dict[str, list[EvalCase]] = {
    "smoke": [
        EvalCase(
            name="status-inspection",
            goal="show me the status of the workspace",
            must_contain=["observed output"],
            must_use_tool="status",
        ),
        EvalCase(
            name="diff-inspection",
            goal="show me the git diff",
            must_contain=["observed output"],
            must_use_tool="git_diff",
        ),
        EvalCase(
            name="memory-listing",
            goal="list the project memory",
            must_contain=["observed output"],
            must_use_tool="memory_list",
        ),
        EvalCase(
            name="honest-fallback",
            goal="tell me a joke",
            must_contain=["mock provider"],
            must_use_tool=None,
        ),
    ],
}


def get_suite(name: str) -> list[EvalCase]:
    if name not in SUITES:
        valid = ", ".join(sorted(SUITES))
        raise OpenTorusError(f"Unknown eval suite '{name}'. Valid suites: {valid}.")
    return SUITES[name]
