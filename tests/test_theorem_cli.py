"""CLI: ``opentorus theorem`` extract / list / show / link / check / review / coverage."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.paths import WORKSPACE_DIRNAME
from opentorus.research.dossier import claims as dossier_claims
from opentorus.research.dossier import store as dossier_store
from opentorus.research.papers import acquire_paper, read_paper
from opentorus.research.sources.base import SourceRecord

runner = CliRunner()

PAGES = [
    "1 Introduction\nWe study finite groups. By Theorem 2.1 we get the bound.\n",
    (
        "2 Main results\n"
        "Theorem 2.1 (Main theorem). Let G be a finite group of order n. "
        "Then every element of G has order dividing n.\n"
        "Proof. Omitted.\n"
        "Lemma 2.2. Suppose H is a subgroup of G. Then |H| divides |G|.\n"
    ),
]


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    ot = tmp_path / WORKSPACE_DIRNAME
    record = SourceRecord(source="arxiv", title="Finite groups", arxiv_id="2401.00001")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF")
    read_paper(ot, paper.id, page_extractor=lambda p: list(PAGES))
    dossier_store.create_dossier(ot, "Every element of a finite group has order dividing |G|.")
    dossier_store.add_assumption(ot, "PROBLEM-0001", "G is a finite group of order n")
    return ot, paper.id


def test_extract_list_show_review_roundtrip(tmp_path: Path, monkeypatch) -> None:
    ot, pid = _setup(tmp_path, monkeypatch)
    res = runner.invoke(app, ["theorem", "extract", pid, "--problem", "PROBLEM-0001"])
    assert res.exit_code == 0, res.stdout
    assert "THMREF-0001" in res.stdout and "THMREF-0002" in res.stdout
    assert "candidate" in res.stdout

    # Nothing new on a second run, still exit 0.
    res = runner.invoke(app, ["theorem", "extract", pid])
    assert res.exit_code == 0 and "No new candidate" in res.stdout

    res = runner.invoke(app, ["theorem", "list", "--json"])
    assert res.exit_code == 0
    rows = json.loads(res.stdout)
    assert [r["id"] for r in rows] == ["THMREF-0001", "THMREF-0002"]
    assert all(r["review_status"] == "candidate" for r in rows)

    res = runner.invoke(
        app, ["theorem", "list", "--problem", "PROBLEM-0001", "--status", "accepted"]
    )
    assert res.exit_code == 0 and "No theorem references" in res.stdout

    res = runner.invoke(app, ["theorem", "show", "THMREF-0001"])
    assert res.exit_code == 0
    assert "Theorem 2.1" in res.stdout and "Main theorem" in res.stdout
    assert "Let G be a finite group" in res.stdout

    res = runner.invoke(app, ["theorem", "show", "THMREF-0001", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert data["id"] == "THMREF-0001" and data["extraction_method"] == "heuristic"
    assert len(data["location_hash"]) == 64

    res = runner.invoke(
        app, ["theorem", "review", "THMREF-0001", "--status", "accepted", "--note", "checked"]
    )
    assert res.exit_code == 0 and "accepted" in res.stdout
    res = runner.invoke(app, ["theorem", "list", "--status", "accepted", "--json"])
    assert [r["id"] for r in json.loads(res.stdout)] == ["THMREF-0001"]

    res = runner.invoke(app, ["theorem", "review", "THMREF-0002", "--status", "verified"])
    assert res.exit_code == 1 and "Unknown review status" in res.stdout

    # Review is where a human classifies: categories feed coverage.
    res = runner.invoke(
        app,
        [
            "theorem",
            "review",
            "THMREF-0002",
            "--status",
            "accepted",
            "--category",
            "standard_tools_lemmas",
            "--root-relation",
            "supporting",
            "--problem",
            "PROBLEM-0001",
        ],
    )
    assert res.exit_code == 0, res.stdout
    res = runner.invoke(app, ["theorem", "show", "THMREF-0002", "--json"])
    data = json.loads(res.stdout)
    assert data["categories"] == ["standard_tools_lemmas"]
    assert data["root_relation"] == "supporting" and data["problem_id"] == "PROBLEM-0001"
    res = runner.invoke(app, ["theorem", "coverage", "PROBLEM-0001", "--json"])
    cov = json.loads(res.stdout)
    assert cov["entries"]["standard_tools_lemmas"]["level"] == "adequate"
    res = runner.invoke(
        app, ["theorem", "review", "THMREF-0002", "--status", "accepted", "--category", "vibes"]
    )
    assert res.exit_code == 1 and "Unknown coverage category" in res.stdout


def test_extract_llm_under_mock_provider_creates_only_what_the_source_confirms(
    tmp_path: Path, monkeypatch
) -> None:
    # The default (mock) provider answers with keyword-driven prose, never a JSON
    # list: nothing is extracted, nothing is invented, exit stays 0.
    _ot, pid = _setup(tmp_path, monkeypatch)
    res = runner.invoke(app, ["theorem", "extract", pid, "--llm"])
    assert res.exit_code == 0, res.stdout
    assert "No new candidate" in res.stdout
    res = runner.invoke(app, ["theorem", "list", "--json"])
    assert json.loads(res.stdout) == []


def test_extract_errors_exit_one(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    res = runner.invoke(app, ["theorem", "extract", "PAPER-0099"])
    assert res.exit_code == 1 and "No paper" in res.stdout
    res = runner.invoke(app, ["theorem", "show", "THMREF-0042"])
    assert res.exit_code == 1 and "No theorem reference" in res.stdout


def test_link_records_relation(tmp_path: Path, monkeypatch) -> None:
    _ot, pid = _setup(tmp_path, monkeypatch)
    assert runner.invoke(app, ["theorem", "extract", pid]).exit_code == 0
    res = runner.invoke(
        app,
        [
            "theorem",
            "link",
            "THMREF-0002",
            "THMREF-0001",
            "--relation",
            "implies",
            "--rationale",
            "Lagrange gives the order bound",
        ],
    )
    assert res.exit_code == 0 and "THMREL-0001" in res.stdout
    res = runner.invoke(app, ["theorem", "show", "THMREF-0001"])
    assert "--implies-->" in res.stdout and "(manual, candidate)" in res.stdout
    res = runner.invoke(
        app, ["theorem", "link", "THMREF-0001", "THMREF-0002", "--relation", "refutes"]
    )
    assert res.exit_code == 1 and "Unknown relation" in res.stdout


def test_check_with_claim_uses_dossier_context_and_exit_codes(tmp_path: Path, monkeypatch) -> None:
    ot, pid = _setup(tmp_path, monkeypatch)
    assert (
        runner.invoke(app, ["theorem", "extract", pid, "--problem", "PROBLEM-0001"]).exit_code == 0
    )
    claim = dossier_claims.add_claim(
        ot,
        "PROBLEM-0001",
        claim_type="CONJECTURE",
        statement="Every element of G has order dividing n.",
    )
    before = [c.model_dump(mode="json") for c in dossier_store.list_claims(ot, "PROBLEM-0001")]

    check_args = [
        "theorem",
        "check",
        "THMREF-0001",
        "--problem",
        "PROBLEM-0001",
        "--claim",
        claim.id,
    ]
    # An unreviewed (candidate) reference never comes out accepted, however well the
    # rest of the checks go: the human review is the gate.
    res = runner.invoke(app, [*check_args, "--json"])
    assert res.exit_code == 0, res.stdout
    unreviewed = json.loads(res.stdout)
    assert unreviewed["result"] == "needs-human-review"
    assert [c["name"] for c in unreviewed["checks"] if c["passed"] is False] == [
        "reference_reviewed"
    ]

    review = ["theorem", "review", "THMREF-0001", "--status", "accepted", "--note", "read it"]
    assert runner.invoke(app, review).exit_code == 0
    res = runner.invoke(app, [*check_args, "--json"])
    assert res.exit_code == 0, res.stdout
    data = json.loads(res.stdout)
    assert data["result"] == "accepted"
    assert data["target_id"] == claim.id
    assert data["assumption_context"] == ["G is a finite group of order n"]
    assert data["claim_text"] == claim.statement
    assert data["id"] == "THMAPP-0002"
    after = [c.model_dump(mode="json") for c in dossier_store.list_claims(ot, "PROBLEM-0001")]
    assert after == before

    # Human-readable output.
    res = runner.invoke(
        app, ["theorem", "check", "THMREF-0001", "--problem", "PROBLEM-0001", "--claim", claim.id]
    )
    assert res.exit_code == 0 and "ACCEPTED" in res.stdout
    assert "not a claim promotion" in res.stdout

    # A rejected result exits 2 (gating), and explains why.
    res = runner.invoke(
        app,
        [
            "theorem",
            "check",
            "THMREF-0001",
            "--problem",
            "PROBLEM-0001",
            "--claim-text",
            "There exists some element of G whose order divides n.",
            "--assume",
            "G is a finite group of order n",
        ],
    )
    assert res.exit_code == 2, res.stdout
    assert "REJECTED" in res.stdout and "quantifier mismatch" in res.stdout

    # Errors exit 1.
    res = runner.invoke(app, ["theorem", "check", "THMREF-0001", "--problem", "PROBLEM-0001"])
    assert res.exit_code == 1 and "--claim" in res.stdout
    res = runner.invoke(
        app,
        ["theorem", "check", "THMREF-0001", "--problem", "PROBLEM-0001", "--claim", "CLAIM-0099"],
    )
    assert res.exit_code == 1 and "No claim" in res.stdout
    res = runner.invoke(
        app,
        [
            "theorem",
            "check",
            "THMREF-0001",
            "--problem",
            "PROBLEM-0001",
            "--claim-text",
            "x",
            "--direction",
            "sideways",
        ],
    )
    assert res.exit_code == 1


def test_coverage_show_and_override(tmp_path: Path, monkeypatch) -> None:
    from opentorus.research.theorems import store

    ot, pid = _setup(tmp_path, monkeypatch)
    # A plain read derives the map and persists nothing: reading twice must not grow
    # the ledger (each COV record is meant to mark a real assessment, not a look).
    res = runner.invoke(app, ["theorem", "coverage", "PROBLEM-0001", "--json"])
    assert res.exit_code == 0, res.stdout
    data = json.loads(res.stdout)
    assert data["id"] == ""  # not recorded
    assert data["entries"]["known_counterexamples"]["level"] == "unknown"
    assert "known_counterexamples" in data["insufficient"]
    assert runner.invoke(app, ["theorem", "coverage", "PROBLEM-0001", "--json"]).exit_code == 0
    assert store.list_coverage_history(ot, "PROBLEM-0001") == []
    res = runner.invoke(app, ["theorem", "coverage", "PROBLEM-0001"])
    assert res.exit_code == 0 and "not recorded" in res.stdout

    # ``--record`` appends exactly one assessment.
    res = runner.invoke(app, ["theorem", "coverage", "PROBLEM-0001", "--record", "--json"])
    assert res.exit_code == 0, res.stdout
    assert json.loads(res.stdout)["id"] == "COV-0001"
    assert [a.id for a in store.list_coverage_history(ot, "PROBLEM-0001")] == ["COV-0001"]

    res = runner.invoke(
        app,
        [
            "theorem",
            "coverage",
            "PROBLEM-0001",
            "--mode",
            "exploration",
            "--set",
            "definitions_notation",
            "adequate",
            "--evidence",
            pid,
            "--note",
            "section 2",
            "--json",
        ],
    )
    assert res.exit_code == 0, res.stdout
    data = json.loads(res.stdout)
    entry = data["entries"]["definitions_notation"]
    assert entry["level"] == "adequate" and entry["provenance"] == "human"
    assert entry["evidence_ids"] == [pid]
    assert "definitions_notation" not in data["insufficient"]
    assert data["mode"] == "exploration"
    assert data["id"] == "COV-0002"  # --set implies a recorded assessment
    assert len(store.list_coverage_history(ot, "PROBLEM-0001")) == 2

    res = runner.invoke(app, ["theorem", "coverage", "PROBLEM-0001"])
    assert res.exit_code == 0
    assert "Insufficient critical categories" in res.stdout
    assert "definitions_notation" in res.stdout

    res = runner.invoke(app, ["theorem", "coverage", "PROBLEM-0001", "--set", "vibes", "adequate"])
    assert res.exit_code == 1 and "Unknown coverage category" in res.stdout


def test_theorem_group_is_registered_and_sorted() -> None:
    res = runner.invoke(app, ["theorem", "--help"])
    assert res.exit_code == 0
    for name in ("check", "coverage", "extract", "link", "list", "review", "show"):
        assert name in res.stdout
