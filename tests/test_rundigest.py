"""The digest replaces reading a transcript by hand.

Every behavioural fix in this project so far came out of manual transcript forensics —
counting repeated failures, spotting search loops, noticing a run that never submitted
anything to a verifier. These tests pin that the digest finds those same patterns, and
that it stays descriptive: it reports what happened and never rules on the mathematics.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.actions import log_action
from opentorus.evals.rundigest import digest_workspace, format_digest
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_uninitialized_workspace_is_reported_not_crashed(tmp_path: Path) -> None:
    digest = digest_workspace(tmp_path / "nope" / ".opentorus")
    assert digest.initialized is False
    assert "not an OpenTorus workspace" in format_digest(digest)


def test_empty_workspace_flags_no_tool_calls(tmp_path: Path) -> None:
    digest = digest_workspace(_ws(tmp_path))
    assert digest.total_calls == 0
    assert any("no tool calls" in flag for flag in digest.flags)


def test_repeated_identical_failure_is_surfaced(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    for _ in range(4):
        log_action(ot, "proof_submit", ok=False, args={"b": "coq"}, stderr_summary="unsolved goals")
    digest = digest_workspace(ot)

    assert digest.total_failures == 4
    assert digest.dead_ends[0].tool == "proof_submit"
    assert digest.dead_ends[0].count == 4
    assert any("4x with the same error" in flag for flag in digest.flags)


def test_distinct_failures_are_not_a_dead_end(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    log_action(ot, "read_file", ok=False, args={}, stderr_summary="Not a file: a")
    log_action(ot, "read_file", ok=False, args={}, stderr_summary="Not a file: b")
    assert digest_workspace(ot).dead_ends == []


def test_search_streak_is_measured_and_broken_by_real_work(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    for _ in range(5):
        log_action(ot, "lit_search", ok=True, args={})
    log_action(ot, "paper_fetch", ok=True, args={})
    for _ in range(2):
        log_action(ot, "lit_search", ok=True, args={})

    digest = digest_workspace(ot)
    assert digest.longest_search_streak == 5
    assert any("consecutive searches" in flag for flag in digest.flags)


def test_inventory_polls_do_not_break_a_search_streak(tmp_path: Path) -> None:
    """paper_list/status are neutral — the loop treats them that way too."""
    ot = _ws(tmp_path)
    log_action(ot, "lit_search", ok=True, args={})
    log_action(ot, "paper_list", ok=True, args={})
    log_action(ot, "lit_search", ok=True, args={})
    assert digest_workspace(ot).longest_search_streak == 2


def test_verifier_outcomes_are_counted_separately(tmp_path: Path) -> None:
    import json

    from opentorus.config import default_config
    from opentorus.research.verifiers.proofs import submit_proof
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    ot = _ws(tmp_path)
    for source in (
        json.dumps({"lhs": "sin(x)**2 + cos(x)**2", "rhs": "1", "relation": "eq"}),
        json.dumps({"lhs": "x + 1", "rhs": "x + 2", "relation": "eq"}),
        "not a certificate",
    ):
        submit_proof(ot, default_config(), "sympy", source, verifier=SymPyVerifier())

    v = digest_workspace(ot).verifier
    assert v.submissions == 3
    assert v.accepted == 1
    assert v.rejected == 1
    # An unreadable certificate is inconclusive, never counted as a refutation.
    assert v.inconclusive == 1


def test_prompt_share_is_reported(tmp_path: Path) -> None:
    from opentorus.usage import UsageRecord, record_usage

    ot = _ws(tmp_path)
    for _ in range(3):
        record_usage(
            ot,
            UsageRecord(
                provider="ollama",
                model="gemma4:31b",
                prompt_tokens=20_000,
                completion_tokens=500,
                latency_ms=25_000,
            ),
        )

    cost = digest_workspace(ot).cost
    assert cost.model_calls == 3
    assert cost.prompt_tokens == 60_000
    assert round(cost.prompt_share, 2) == 0.98
    assert any("re-sent prompt" in flag for flag in digest_workspace(ot).flags)


def test_digest_makes_no_claim_about_the_mathematics(tmp_path: Path) -> None:
    """The flags describe process. Correctness is never inferred from them."""
    ot = _ws(tmp_path)
    log_action(ot, "proof_write", ok=True, args={})
    text = format_digest(digest_workspace(ot)).lower()
    for verdict in ("proved", "correct", "solved", "wrong"):
        assert verdict not in text


def test_cli_digest_accepts_a_project_root(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    log_action(workspace_dir(tmp_path), "status", ok=True, args={})

    result = runner.invoke(app, ["eval", "digest", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "Run digest" in result.stdout
    assert "status" in result.stdout
