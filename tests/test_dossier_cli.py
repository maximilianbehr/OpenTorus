"""CLI-level tests for the blessed M1 problem workflow."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.paths import WORKSPACE_DIRNAME

runner = CliRunner()


def _init(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0


def test_problem_new_and_show(tmp_path: Path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    res = runner.invoke(app, ["problem", "new", "Prove or refute: X holds.", "--domain", "algebra"])
    assert res.exit_code == 0
    assert "PROBLEM-0001" in res.stdout
    dossier_dir = tmp_path / WORKSPACE_DIRNAME / "problems" / "PROBLEM-0001"
    assert (dossier_dir / "problem.yaml").is_file()
    assert (dossier_dir / "statement.md").is_file()

    res = runner.invoke(app, ["problem", "show", "PROBLEM-0001"])
    assert res.exit_code == 0
    assert "PROBLEM-0001" in res.stdout
    assert "open" in res.stdout


def test_problem_show_attributes_workspace_research_store(tmp_path: Path, monkeypatch) -> None:
    # The agent's claim/evidence/exp tools write to the workspace-global research
    # store, stamped with the active problem id; `problem show` must report the
    # counts attributed to this dossier, not silently show 0.
    from opentorus.research.claims import new_claim
    from opentorus.workspace import workspace_dir

    _init(tmp_path, monkeypatch)
    runner.invoke(app, ["problem", "new", "Prove or refute: X holds."])
    base = workspace_dir(tmp_path)
    new_claim(base, "A claim attributed to this problem.", problem_id="PROBLEM-0001")

    res = runner.invoke(app, ["problem", "show", "PROBLEM-0001"])
    assert res.exit_code == 0
    assert "research store (attributed to this problem)" in res.stdout
    assert "claims: 1" in res.stdout  # the attributed claim is counted and surfaced


def test_problem_show_counts_legacy_untagged_in_single_dossier(tmp_path: Path, monkeypatch) -> None:
    # Legacy artifacts created before attribution carry no problem_id. In a workspace
    # with exactly one dossier they can only belong to it, so they are counted here.
    from opentorus.research.claims import new_claim
    from opentorus.workspace import workspace_dir

    _init(tmp_path, monkeypatch)
    runner.invoke(app, ["problem", "new", "Prove or refute: Y holds."])
    new_claim(workspace_dir(tmp_path), "Legacy untagged claim.")  # problem_id=None

    res = runner.invoke(app, ["problem", "show", "PROBLEM-0001"])
    assert res.exit_code == 0
    assert "research store (attributed to this problem)" in res.stdout
    assert "claims: 1" in res.stdout


def test_full_workflow_produces_honest_report(tmp_path: Path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    runner.invoke(app, ["problem", "new", "Conjecture: X holds for all n."])
    assert (
        runner.invoke(
            app, ["problem", "attack", "PROBLEM-0001", "--strategy", "special_cases"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["problem", "claim", "PROBLEM-0001", "--type", "CONJECTURE", "--statement", "X holds"],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "problem",
                "experiment",
                "PROBLEM-0001",
                "--title",
                "sweep",
                "--command",
                "python3 -c 'print(1)'",
                "--seed",
                "3",
                "--run",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "problem",
                "evidence",
                "PROBLEM-0001",
                "--claim",
                "CLAIM-0001",
                "--type",
                "EXPERIMENT",
                "--summary",
                "held to 10^4",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "problem",
                "attempt",
                "PROBLEM-0001",
                "--method",
                "induction",
                "--reason",
                "base case fails",
            ],
        ).exit_code
        == 0
    )

    res = runner.invoke(app, ["problem", "report", "PROBLEM-0001"])
    assert res.exit_code == 0
    report = (tmp_path / WORKSPACE_DIRNAME / "problems" / "PROBLEM-0001" / "report.md").read_text()
    assert "## Claims and Evidence" in report
    assert "## Failed Attempts" in report

    lint = runner.invoke(app, ["problem", "report", "PROBLEM-0001", "--lint"])
    assert lint.exit_code == 0
    assert "No honesty warnings" in lint.stdout


def test_problem_show_prints_full_multiline_statement(tmp_path: Path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    from opentorus.research.dossier.store import create_dossier

    base = tmp_path / WORKSPACE_DIRNAME
    body = (
        "Problem 6.3 (notes.md):\n\n"
        "## Background\n\n"
        "Let $\\varepsilon_m^{*}$ denote the optimal error.\n\n"
        "**Problem 6.3.** What is the asymptotic behaviour?"
    )
    dossier = create_dossier(base, body, title="Problem 6.3", tags=["label:6.3"])

    res = runner.invoke(app, ["problem", "show", dossier.id])
    assert res.exit_code == 0
    assert "Background" in res.stdout
    assert "asymptotic behaviour" in res.stdout
    assert "optimal error" in res.stdout


def test_problem_show_after_extract(tmp_path: Path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    from opentorus.research.dossier.store import create_dossier

    base = tmp_path / WORKSPACE_DIRNAME
    dossier = create_dossier(
        base,
        "Sketch-and-solve: let A be a full-rank matrix and prove the bound.",
        title="Problem 5.1",
        tags=["PAPER-0001", "label:5.1"],
    )

    res = runner.invoke(app, ["problem", "show", dossier.id])
    assert res.exit_code == 0
    assert dossier.id in res.stdout
    assert "Sketch-and-solve" in res.stdout

    missing = runner.invoke(app, ["problem", "show", "PROBLEM-9999"])
    assert missing.exit_code == 1


def test_problem_extract_without_verbose_hides_llm_trace(tmp_path: Path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    from opentorus.research.papers import add_paper
    from opentorus.workspace import workspace_dir

    base = workspace_dir(tmp_path)
    paper = add_paper(base, "https://example.com/x.pdf")
    text_file = base / "papers" / paper.id / "text.txt"
    text_file.parent.mkdir(parents=True, exist_ok=True)
    text_file.write_text(
        "Open Problems\n\n5.1) Prove the sketch-and-solve bound for all full-rank A.\n",
        encoding="utf-8",
    )
    import yaml

    from opentorus.research.papers import get_paper

    meta_paper = get_paper(base, paper.id)
    assert meta_paper is not None
    meta_paper.text_path = str(text_file.relative_to(base))
    meta = base / "papers" / paper.id / "metadata.yaml"
    meta.write_text(yaml.safe_dump(meta_paper.model_dump(mode="json"), sort_keys=False))

    class _OllamaLike:
        name = "ollama"
        supports_streaming = True

        def respond(self, messages, tools=None, on_text=None, *, stream=False, on_thinking=None):
            from opentorus.providers.base import ProviderResponse

            if stream and on_thinking:
                on_thinking("secret reasoning")
            if stream and on_text:
                on_text('[{"label":"5.1","statement":"Prove bound","section":"Open"}]')
            return ProviderResponse(
                kind="message",
                content='[{"label":"5.1","statement":"Prove bound","section":"Open"}]',
            )

    monkeypatch.setattr("opentorus.providers.registry.get_provider", lambda config: _OllamaLike())

    res = runner.invoke(app, ["problem", "extract", "--llm-only", paper.id])
    assert res.exit_code == 0
    assert "LLM request" not in res.stdout
    assert "secret reasoning" not in res.stdout
    assert "PROBLEM-0001" in res.stdout

    traced = runner.invoke(app, ["--verbose", "problem", "extract", "--llm-only", paper.id])
    assert traced.exit_code == 0
    assert "Finding open problems" in traced.stdout or "LLM request" in traced.stdout


def test_problem_extract_llm_only_requires_provider(tmp_path: Path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    from opentorus.research.papers import add_paper
    from opentorus.workspace import workspace_dir

    add_paper(workspace_dir(tmp_path), "https://example.com/x.pdf")
    res = runner.invoke(app, ["problem", "extract", "--llm-only", "PAPER-0001"])
    assert res.exit_code == 1
    assert "needs a configured model provider" in res.stdout

    both = runner.invoke(
        app, ["problem", "extract", "--llm-only", "--heuristic-only", "PAPER-0001"]
    )
    assert both.exit_code == 1
    assert "cannot be combined" in both.stdout


def test_invalid_claim_type_rejected(tmp_path: Path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    runner.invoke(app, ["problem", "new", "X holds."])
    res = runner.invoke(
        app, ["problem", "claim", "PROBLEM-0001", "--type", "PROVEN", "--statement", "X"]
    )
    assert res.exit_code == 1
    assert "Unknown claim type" in res.stdout


def test_unverified_counterexample_blocked_via_cli(tmp_path: Path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    runner.invoke(app, ["problem", "new", "X holds."])
    res = runner.invoke(
        app,
        [
            "problem",
            "claim",
            "PROBLEM-0001",
            "--type",
            "COUNTEREXAMPLE_VERIFIED",
            "--statement",
            "n=5 refutes X",
        ],
    )
    assert res.exit_code == 1
    assert "verification artifact" in res.stdout
