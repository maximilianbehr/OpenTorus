"""The agent can never take a human decision through the shell.

Accepting a frozen formal statement defines what ``formally_verified`` means for a
claim, and deciding a queued approval authorises an action: both are reserved for
the person, so the command policy blocks them in every mode.
"""

from __future__ import annotations

import pytest

from opentorus.permissions.policy import evaluate_command, is_dangerous_command
from opentorus.tools.effects import BUILTIN_EFFECTS


@pytest.mark.parametrize(
    "command",
    [
        "opentorus proof statement accept FSTMT-0001 --yes",
        "python -m opentorus proof statement accept FSTMT-0001 --yes",
        "cd w && opentorus approvals approve APR-1",
        "opentorus approvals deny APR-1",
    ],
)
@pytest.mark.parametrize("mode", ["safe", "ask", "trusted"])
def test_self_approval_commands_are_always_blocked(command: str, mode: str) -> None:
    assert is_dangerous_command(command)
    assert not evaluate_command(command, mode).allowed  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "command",
    ["opentorus proof statement list", "opentorus approvals list", "opentorus status"],
)
def test_read_only_decision_views_stay_allowed(command: str) -> None:
    assert not is_dangerous_command(command)


def test_proof_submit_has_an_explicit_effect_class() -> None:
    assert BUILTIN_EFFECTS["proof_submit"] == "compensatable"
