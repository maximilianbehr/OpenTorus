"""Tests for the approvals UX (Milestone 34)."""

from __future__ import annotations

from opentorus.approvals import (
    SessionApprovals,
    can_blanket,
    confirm_with_approvals,
)
from opentorus.permissions.policy import PermissionDecision


def _decision(risk: str = "medium", allowed: bool = True) -> PermissionDecision:
    return PermissionDecision(
        allowed=allowed,
        reason="test",
        requires_confirmation=True,
        risk_level=risk,  # type: ignore[arg-type]
    )


def test_can_blanket_only_low_medium() -> None:
    assert can_blanket(_decision("low"))
    assert can_blanket(_decision("medium"))
    assert not can_blanket(_decision("high"))
    assert not can_blanket(_decision("blocked", allowed=False))


def test_allow_once_does_not_persist() -> None:
    approvals = SessionApprovals()
    calls = {"n": 0}

    def ask(decision, description, blanket):
        calls["n"] += 1
        return "once"

    d = _decision("medium")
    assert confirm_with_approvals(d, "write foo.py", approvals=approvals, ask=ask)
    # A second identical request must ask again (nothing remembered).
    assert confirm_with_approvals(d, "write foo.py", approvals=approvals, ask=ask)
    assert calls["n"] == 2
    assert len(approvals) == 0


def test_allow_session_persists_for_blanket_eligible() -> None:
    approvals = SessionApprovals()
    calls = {"n": 0}

    def ask(decision, description, blanket):
        calls["n"] += 1
        return "session"

    d = _decision("medium")
    assert confirm_with_approvals(d, "write foo.py", approvals=approvals, ask=ask)
    # Second identical request is auto-approved without asking.
    assert confirm_with_approvals(d, "write foo.py", approvals=approvals, ask=ask)
    assert calls["n"] == 1
    assert len(approvals) == 1


def test_high_risk_can_never_be_blanket_approved() -> None:
    approvals = SessionApprovals()
    calls = {"n": 0}

    def ask(decision, description, blanket):
        calls["n"] += 1
        # Even if the user tries to pick session, the action is not eligible.
        return "session"

    d = _decision("high")
    assert confirm_with_approvals(d, "rm -rf build", approvals=approvals, ask=ask)
    # Still asks again -- high risk is never remembered.
    assert confirm_with_approvals(d, "rm -rf build", approvals=approvals, ask=ask)
    assert calls["n"] == 2
    assert len(approvals) == 0


def test_deny_blocks() -> None:
    approvals = SessionApprovals()

    def ask(decision, description, blanket):
        return "deny"

    assert not confirm_with_approvals(
        _decision("medium"), "write foo.py", approvals=approvals, ask=ask
    )


def test_console_confirm_session_then_auto() -> None:
    from opentorus.approvals import make_console_confirm

    class FakeConsole:
        def __init__(self, answers):
            self._answers = list(answers)
            self.prompts: list[str] = []

        def print(self, *args, **kwargs):
            pass

        def input(self, prompt):
            self.prompts.append(prompt)
            return self._answers.pop(0)

    console = FakeConsole(["s"])
    confirm = make_console_confirm(console)
    d = _decision("medium")
    assert confirm(d, "write foo.py")
    # Second call auto-approves; no further input consumed.
    assert confirm(d, "write foo.py")
    assert len(console.prompts) == 1


def test_console_confirm_high_risk_hides_session_option() -> None:
    from opentorus.approvals import make_console_confirm

    class FakeConsole:
        def __init__(self, answers):
            self._answers = list(answers)
            self.prompts: list[str] = []

        def print(self, *args, **kwargs):
            pass

        def input(self, prompt):
            self.prompts.append(prompt)
            return self._answers.pop(0)

    # User types 's' on a high-risk action -> treated as allow-once, not session.
    console = FakeConsole(["s", "y"])
    confirm = make_console_confirm(console)
    d = _decision("high")
    assert confirm(d, "rm -rf build")
    assert confirm(d, "rm -rf build")
    assert len(console.prompts) == 2
    assert "this session" not in console.prompts[0]


def test_console_confirm_accepts_full_words_shown_in_prompt() -> None:
    """The prompt shows the words 'once'/'this session'/'no'; typing them must work.

    Regression: Rich stripped the ``[y]``/``[s]``/``[n]`` key hints as markup, so
    users only saw the words and naturally typed e.g. 'once' -- which used to be
    treated as a denial, causing the action to loop.
    """
    from opentorus.approvals import make_console_confirm

    class FakeConsole:
        def __init__(self, answers):
            self._answers = list(answers)
            self.prompts: list[str] = []

        def print(self, *args, **kwargs):
            pass

        def input(self, prompt):
            self.prompts.append(prompt)
            return self._answers.pop(0)

    confirm = make_console_confirm(FakeConsole(["once"]))
    assert confirm(_decision("medium"), "lit_search")

    approvals = SessionApprovals()
    confirm = make_console_confirm(FakeConsole(["this session"]), approvals)
    d = _decision("medium")
    assert confirm(d, "lit_search")
    # 'this session' must blanket-approve so the next identical call is silent.
    assert confirm(d, "lit_search")
    assert len(approvals) == 1

    confirm = make_console_confirm(FakeConsole(["no"]))
    assert not confirm(_decision("medium"), "lit_search")


def test_external_session_covers_all_external_tools() -> None:
    from opentorus.approvals import EXTERNAL_SESSION_KEY, confirm_with_approvals

    approvals = SessionApprovals()
    calls = {"n": 0}

    def ask(decision, description, blanket):
        calls["n"] += 1
        return "session"

    d = _decision("medium")
    assert confirm_with_approvals(
        d,
        "lit_search",
        approvals=approvals,
        ask=ask,
        session_scope=EXTERNAL_SESSION_KEY,
    )
    assert confirm_with_approvals(
        d,
        "web_search",
        approvals=approvals,
        ask=ask,
        session_scope=EXTERNAL_SESSION_KEY,
    )
    assert confirm_with_approvals(
        d,
        "fetch_url",
        approvals=approvals,
        ask=ask,
        session_scope=EXTERNAL_SESSION_KEY,
    )
    assert calls["n"] == 1
    assert approvals.approved(EXTERNAL_SESSION_KEY)
