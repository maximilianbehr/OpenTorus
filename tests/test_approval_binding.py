"""Approvals keyed on (tool, canonical args) (6f), effect classes (6h), approval queue (24)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.agent.control.policies.permissions import enforce_permission
from opentorus.approvals import (
    ApprovalQueue,
    SessionApprovals,
    approval_scope,
    confirm_with_approvals,
    describe_action,
    make_queue_confirm,
)
from opentorus.permissions.policy import POLICY_VERSION, PermissionDecision
from opentorus.tools.base import Tool, ToolCall, ToolResult
from opentorus.tools.builtin import (
    ApplyPatchTool,
    FetchUrlTool,
    GitDiffTool,
    LiteratureSearchTool,
    ReadFileTool,
    RunShellTool,
    WebSearchTool,
    WriteFileTool,
)
from opentorus.tools.effects import BUILTIN_EFFECTS, EFFECTS, UnknownOutcomeGuard, effect_of
from opentorus.tools.registry import ToolRegistry


def _decision(risk: str = "medium") -> PermissionDecision:
    return PermissionDecision(
        allowed=True, reason="needs confirmation", requires_confirmation=True, risk_level=risk
    )


def _session_confirm():  # noqa: ANN202
    approvals = SessionApprovals()
    asked: list[tuple[str, bool]] = []

    def ask(decision, description, blanket):  # noqa: ANN001, ANN202
        asked.append((description, blanket))
        return "session"

    def confirm(decision, description, scope=None):  # noqa: ANN001, ANN202
        return confirm_with_approvals(
            decision, description, approvals=approvals, ask=ask, session_scope=scope
        )

    return confirm, asked


def _registry(tmp_path: Path) -> ToolRegistry:
    reg = ToolRegistry()
    for tool in (
        WriteFileTool(tmp_path),
        ApplyPatchTool(tmp_path),
        RunShellTool(tmp_path),
        FetchUrlTool(),
        WebSearchTool(),
    ):
        reg.register(tool)
    return reg


def _enforce(reg, tmp_path, confirm, name, args):  # noqa: ANN001, ANN202
    (tmp_path / ".opentorus").mkdir(exist_ok=True)
    return enforce_permission(
        name, args, _decision(), ot_dir=tmp_path / ".opentorus", registry=reg, confirm=confirm
    )


# --- 6f ---------------------------------------------------------------------------


def test_session_approval_of_write_file_does_not_cover_apply_patch(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    confirm, asked = _session_confirm()
    assert _enforce(reg, tmp_path, confirm, "write_file", {"path": "x.py", "content": "a"}) is None
    assert _enforce(reg, tmp_path, confirm, "write_file", {"path": "x.py", "content": "b"}) is None
    assert len(asked) == 1  # same tool + same path: covered
    _enforce(reg, tmp_path, confirm, "apply_patch", {"path": "x.py", "old": "a", "new": "b"})
    assert len(asked) == 2  # a different tool on the same path asks again
    _enforce(reg, tmp_path, confirm, "write_file", {"path": "y.py", "content": "a"})
    assert len(asked) == 3


def test_external_session_approval_is_per_tool_and_host(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    confirm, asked = _session_confirm()
    _enforce(reg, tmp_path, confirm, "fetch_url", {"url": "https://en.wikipedia.org/a"})
    _enforce(reg, tmp_path, confirm, "fetch_url", {"url": "https://en.wikipedia.org/b"})
    assert len(asked) == 1
    _enforce(reg, tmp_path, confirm, "fetch_url", {"url": "https://evil.example/x"})
    assert len(asked) == 2  # another host
    _enforce(reg, tmp_path, confirm, "web_search", {"query": "x"})
    assert len(asked) == 3  # another external tool is not covered


def test_mcp_session_key_carries_the_server() -> None:
    class _Mcp(Tool):
        permission = "external"
        input_schema: dict = {}
        description = ""

        def __init__(self, server: str) -> None:
            self.server = server
            self.name = f"mcp__{server}__query"

        def run(self, call: ToolCall) -> ToolResult:  # pragma: no cover
            return self.ok(call, "")

    assert str(approval_scope(_Mcp("a"), {})) != str(approval_scope(_Mcp("b"), {}))


def test_prompt_shows_url_and_write_summary(tmp_path: Path) -> None:
    assert describe_action(FetchUrlTool(), {"url": "https://x.org/p?q=1"}) == (
        "fetch_url https://x.org/p?q=1"
    )
    (tmp_path / "f.py").write_text("old line\n", encoding="utf-8")
    text = describe_action(
        WriteFileTool(tmp_path), {"path": "f.py", "content": "new line\n"}, tmp_path
    )
    assert "write_file f.py" in text
    assert "overwrites 9 chars with 9 chars" in text
    assert "-old line" in text and "+new line" in text
    new = describe_action(WriteFileTool(tmp_path), {"path": "n.py", "content": "abc"}, tmp_path)
    assert "new file, 3 chars" in new


def test_policy_version_is_recorded_on_decisions() -> None:
    assert _decision().model_dump()["policy_version"] == POLICY_VERSION


# --- 6h ---------------------------------------------------------------------------


def test_every_builtin_tool_has_an_effect_class(tmp_path: Path) -> None:
    from opentorus.config import default_config
    from opentorus.tools.builtin import build_default_registry

    registry = build_default_registry(tmp_path, tmp_path / ".opentorus", default_config())
    for tool in registry.tools():
        assert effect_of(tool) in EFFECTS
        if tool.name != "proof_submit":  # owned by the Lean worker; derived by default
            assert tool.name in BUILTIN_EFFECTS or tool.effect is not None, tool.name
    assert effect_of(ReadFileTool(tmp_path)) == "observation"
    assert effect_of(GitDiffTool(tmp_path)) == "observation"
    assert effect_of(WriteFileTool(tmp_path)) == "reversible"
    assert effect_of(RunShellTool(tmp_path)) == "irreversible"
    assert effect_of(LiteratureSearchTool(default_config())) == "observation"


def test_irreversible_calls_are_never_session_approved(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    confirm, asked = _session_confirm()
    _enforce(reg, tmp_path, confirm, "run_shell", {"command": "python run.py"})
    _enforce(reg, tmp_path, confirm, "run_shell", {"command": "python run.py"})
    assert len(asked) == 2
    assert all(blanket is False for _, blanket in asked)  # [s] not even offered


def test_unknown_outcome_blocks_the_identical_repeat_only() -> None:
    guard = UnknownOutcomeGuard()
    shell = RunShellTool(Path("."))
    guard.note(shell, {"command": "sbatch x"}, {"outcome": "unknown", "op_id": "ot-1"})
    refusal = guard.refusal(shell, {"command": "sbatch x"})
    assert refusal is not None and "ot-1" in refusal
    assert guard.refusal(shell, {"command": "squeue"}) is None
    # Observation calls may simply be asked again.
    read = ReadFileTool(Path("."))
    guard.note(read, {"path": "a"}, {"outcome": "unknown"})
    assert guard.refusal(read, {"path": "a"}) is None


def test_turn_runner_refuses_to_repeat_an_unknown_outcome_call(tmp_path: Path) -> None:
    from opentorus.config import default_config
    from opentorus.providers.mock_provider import MockProvider
    from opentorus.workspace import init_workspace

    init_workspace(tmp_path)

    class _Submit(Tool):
        name = "submit_job"
        description = "submits"
        input_schema: dict = {"type": "object", "properties": {}}
        effect = "irreversible"
        calls = 0

        def run(self, call: ToolCall) -> ToolResult:
            type(self).calls += 1
            return self.fail(call, "timed out", outcome="unknown", op_id="ot-op-1")

    from opentorus.agent.control.turn_runner import TurnRunner

    registry = ToolRegistry()
    registry.register(_Submit())
    config = default_config()
    config.permissions.mode = "trusted"
    runner = TurnRunner(
        tmp_path, tmp_path / ".opentorus", MockProvider(), registry, config, session_id="s"
    )
    first = runner.execute_tool("submit_job", {"n": 1}, "c1")
    second = runner.execute_tool("submit_job", {"n": 1}, "c2")
    assert _Submit.calls == 1
    assert not first.ok and not second.ok
    assert "unknown outcome" in second.content


# --- 24 ---------------------------------------------------------------------------


def test_queue_records_a_pending_request_and_denies_without_wait(tmp_path: Path) -> None:
    confirm = make_queue_confirm(tmp_path, wait_seconds=0)
    scope = approval_scope(RunShellTool(tmp_path), {"command": "python run.py"})
    assert confirm(_decision(), "python run.py", scope) is False
    pending = ApprovalQueue(tmp_path).list("pending")
    assert len(pending) == 1
    rec = pending[0]
    assert rec["tool"] == "run_shell" and rec["policy_version"] == POLICY_VERSION
    # Asking again does not pile up duplicates.
    confirm(_decision(), "python run.py", scope)
    assert len(ApprovalQueue(tmp_path).list("pending")) == 1


def test_approval_applies_only_to_the_exact_args_and_only_once(tmp_path: Path) -> None:
    queue = ApprovalQueue(tmp_path)
    confirm = make_queue_confirm(tmp_path, wait_seconds=0)
    shell = RunShellTool(tmp_path)
    scope = approval_scope(shell, {"command": "python run.py"})
    confirm(_decision(), "python run.py", scope)
    approval_id = queue.list("pending")[0]["id"]
    queue.decide(approval_id, True)

    other = approval_scope(shell, {"command": "python run.py --all"})
    assert confirm(_decision(), "python run.py --all", other) is False  # changed args
    assert confirm(_decision(), "python run.py", scope) is True  # exact args: approved
    assert confirm(_decision(), "python run.py", scope) is False  # single use: reuse refused
    states = {r["id"]: r["state"] for r in queue.list()}
    assert states[approval_id] == "used"


def test_approval_from_another_policy_version_does_not_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentorus import approvals as approvals_module

    queue = ApprovalQueue(tmp_path)
    confirm = make_queue_confirm(tmp_path, wait_seconds=0)
    scope = approval_scope(RunShellTool(tmp_path), {"command": "make"})
    confirm(_decision(), "make", scope)
    queue.decide(queue.list("pending")[0]["id"], True)
    monkeypatch.setattr(approvals_module, "POLICY_VERSION", "future-version")
    assert confirm(_decision(), "make", scope) is False


def test_queue_waits_for_a_decision(tmp_path: Path) -> None:
    queue = ApprovalQueue(tmp_path)
    scope = approval_scope(RunShellTool(tmp_path), {"command": "python long.py"})
    decided: list[str] = []

    def fake_sleep(seconds: float) -> None:
        pending = queue.list("pending")
        if pending and not decided:
            decided.append(pending[0]["id"])
            queue.decide(pending[0]["id"], True)

    confirm = make_queue_confirm(tmp_path, wait_seconds=30, poll_seconds=0.01, sleep=fake_sleep)
    assert confirm(_decision(), "python long.py", scope) is True
    assert decided


def test_queue_denial_is_respected(tmp_path: Path) -> None:
    queue = ApprovalQueue(tmp_path)
    scope = approval_scope(RunShellTool(tmp_path), {"command": "rm build/x"})

    def fake_sleep(seconds: float) -> None:
        for rec in queue.list("pending"):
            queue.decide(rec["id"], False)

    confirm = make_queue_confirm(tmp_path, wait_seconds=30, poll_seconds=0.01, sleep=fake_sleep)
    assert confirm(_decision(), "rm build/x", scope) is False


def test_approvals_cli_lists_and_decides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app
    from opentorus.workspace import init_workspace

    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    ot = tmp_path / ".opentorus"
    confirm = make_queue_confirm(ot, wait_seconds=0)
    confirm(_decision(), "python run.py", approval_scope(RunShellTool(tmp_path), {"command": "x"}))
    approval_id = ApprovalQueue(ot).list("pending")[0]["id"]
    runner = CliRunner()
    listed = runner.invoke(app, ["approvals", "list"])
    assert listed.exit_code == 0 and approval_id in listed.output
    approved = runner.invoke(app, ["approvals", "approve", approval_id])
    assert approved.exit_code == 0, approved.output
    again = runner.invoke(app, ["approvals", "deny", approval_id])
    assert again.exit_code == 1  # no longer pending
