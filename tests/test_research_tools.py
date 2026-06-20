"""Tests for research agent tools (papers, memory, claims, evidence, experiments)."""

from __future__ import annotations

from pathlib import Path

from opentorus.config import Config
from opentorus.research.claims import new_claim
from opentorus.research.experiments import new_experiment
from opentorus.research.papers import inbox_dir
from opentorus.tools.base import ToolCall
from opentorus.tools.builtin import build_default_registry
from opentorus.tools.research import (
    ClaimNewTool,
    ExpRunTool,
    MemoryAddTool,
    PaperIngestInboxTool,
    PaperListTool,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    init_workspace(root)
    return root, workspace_dir(root)


def test_registry_registers_research_tools(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    registry = build_default_registry(root, ot, Config())
    names = registry.names()
    for name in (
        "paper_list",
        "paper_read",
        "paper_add",
        "paper_fetch",
        "paper_ingest_inbox",
        "memory_add",
        "claim_new",
        "evidence_add",
        "exp_run",
    ):
        assert name in names


def test_paper_list_empty(tmp_path: Path) -> None:
    _, ot = _ws(tmp_path)
    result = PaperListTool(ot).run(ToolCall(name="paper_list", args={}))
    assert result.ok is True
    assert "No papers" in result.content


def test_paper_ingest_inbox_tool(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    (inbox_dir(root) / "drop.pdf").write_bytes(b"%PDF-1.4 drop")
    result = PaperIngestInboxTool(root, ot).run(ToolCall(name="paper_ingest_inbox", args={}))
    assert result.ok is True
    assert "PAPER-0001" in result.content
    assert result.metadata["count"] == 1


def test_memory_and_claim_tools(tmp_path: Path) -> None:
    _, ot = _ws(tmp_path)
    mem = MemoryAddTool(ot).run(
        ToolCall(name="memory_add", args={"text": "Crouzeix constant ≤ 2", "kind": "facts"})
    )
    assert mem.ok is True
    assert "FACT-" in mem.content

    claim = ClaimNewTool(ot).run(
        ToolCall(name="claim_new", args={"statement": "The ratio is at most 2."})
    )
    assert claim.ok is True
    assert "CLAIM-0001" in claim.content


def test_exp_run_returns_summary(tmp_path: Path) -> None:
    _, ot = _ws(tmp_path)
    exp = new_experiment(ot, "quick check")
    (ot / exp.path / "run.py").write_text("print('hello exp')\n", encoding="utf-8")
    result = ExpRunTool(ot).run(ToolCall(name="exp_run", args={"exp_id": exp.id}))
    assert result.ok is True
    assert "exit_code=0" in result.content
    assert "hello exp" in result.content or "summary" in result.content.lower()


def test_evidence_add_links_claim(tmp_path: Path) -> None:
    from opentorus.tools.research import EvidenceAddTool

    _, ot = _ws(tmp_path)
    claim = new_claim(ot, "test claim")
    exp = new_experiment(ot, "supporting run")
    result = EvidenceAddTool(ot).run(
        ToolCall(
            name="evidence_add",
            args={
                "claim_id": claim.id,
                "source_type": "experiment",
                "source_id": exp.id,
                "summary": "Ran without error.",
            },
        )
    )
    assert result.ok is True
    assert claim.id in result.content


def test_agent_tools_attribute_artifacts_to_active_problem(tmp_path: Path) -> None:
    # When a problem is active, claims/evidence/experiments the agent creates in the
    # workspace-global store are stamped with that problem id (attribution).
    from opentorus.research.claims import list_claims
    from opentorus.research.dossier import store
    from opentorus.research.evidence import list_evidence
    from opentorus.research.experiments import list_experiments
    from opentorus.tools.research import EvidenceAddTool, ExpNewTool

    _, ot = _ws(tmp_path)
    store.create_dossier(ot, "Prove X.", title="X")  # also sets the active problem

    claim = ClaimNewTool(ot).run(ToolCall(name="claim_new", args={"statement": "Bound holds."}))
    assert claim.ok is True
    ExpNewTool(ot).run(ToolCall(name="exp_new", args={"title": "sweep"}))
    EvidenceAddTool(ot).run(
        ToolCall(
            name="evidence_add",
            args={"claim_id": "CLAIM-0001", "source_type": "experiment", "summary": "ok"},
        )
    )

    assert [c.problem_id for c in list_claims(ot)] == ["PROBLEM-0001"]
    assert [e.problem_id for e in list_evidence(ot)] == ["PROBLEM-0001"]
    assert [x.problem_id for x in list_experiments(ot)] == ["PROBLEM-0001"]
    # The per-problem filters return exactly those artifacts.
    assert len(list_claims(ot, problem_id="PROBLEM-0001")) == 1
    assert len(list_claims(ot, problem_id="PROBLEM-9999")) == 0


def test_agent_tools_leave_problem_id_none_without_active_problem(tmp_path: Path) -> None:
    # With no active problem, artifacts are created unattributed (problem_id None),
    # preserving the prior behavior for non-dossier research workflows.
    from opentorus.research.claims import list_claims

    _, ot = _ws(tmp_path)
    ClaimNewTool(ot).run(ToolCall(name="claim_new", args={"statement": "Unscoped claim."}))
    assert list_claims(ot)[0].problem_id is None


def test_paper_fetch_normalizes_arxiv_url(tmp_path: Path, monkeypatch) -> None:
    from opentorus.config import default_config
    from opentorus.research.papers import acquire_paper
    from opentorus.research.sources.base import SourceRecord
    from opentorus.tools.research import PaperFetchTool

    root, ot = _ws(tmp_path)
    record = SourceRecord(source="arxiv", title="URL paper", arxiv_id="2504.01500")
    acquire_paper(ot, record, downloader=lambda u: b"%PDF fake")

    config = default_config()
    config.permissions.mode = "trusted"
    result = PaperFetchTool(ot, config).run(
        ToolCall(
            name="paper_fetch",
            args={"identifier": "https://arxiv.org/abs/2504.01500"},
        )
    )
    assert result.ok is True
    assert "PAPER-0001" in result.content


def test_paper_fetch_rejects_paper_id(tmp_path: Path) -> None:
    from opentorus.config import default_config
    from opentorus.tools.research import PaperFetchTool

    _, ot = _ws(tmp_path)
    config = default_config()
    result = PaperFetchTool(ot, config).run(
        ToolCall(name="paper_fetch", args={"identifier": "PAPER-0001"})
    )
    assert result.ok is False
    assert "Unrecognized" in result.content or "PAPER-0001" in result.content


def test_tool_specs_include_examples(tmp_path: Path) -> None:
    root, ot = _ws(tmp_path)
    tool = build_default_registry(root, ot, Config()).get("paper_fetch")
    assert tool is not None
    spec = tool.to_spec()
    assert "2504.01500" in spec["description"]
    assert "Example:" in spec["description"]


def test_paper_list_shows_fetch_identifier(tmp_path: Path) -> None:
    from opentorus.research.papers import acquire_paper
    from opentorus.research.sources.base import SourceRecord
    from opentorus.tools.research import PaperListTool

    _, ot = _ws(tmp_path)
    acquire_paper(
        ot,
        SourceRecord(source="arxiv", title="Sign", arxiv_id="2504.01500"),
        downloader=lambda u: b"%PDF fake",
    )
    result = PaperListTool(ot).run(ToolCall(name="paper_list", args={}))
    assert result.ok
    assert 'fetch="2504.01500"' in result.content


def test_paper_fetch_auto_reads_cached_pdf(tmp_path: Path, monkeypatch) -> None:
    from opentorus.config import default_config
    from opentorus.research.papers import acquire_paper, is_paper_parsed
    from opentorus.research.sources.base import SourceRecord
    from opentorus.tools.research import PaperFetchTool
    from test_paper_extraction import FIXTURE_PAGES

    root, ot = _ws(tmp_path)
    record = SourceRecord(source="arxiv", title="Auto read", arxiv_id="2401.88888")
    paper = acquire_paper(ot, record, downloader=lambda u: b"%PDF fake")
    assert is_paper_parsed(ot, paper) is False

    import opentorus.research.papers as papers_mod

    original_read = papers_mod.read_paper

    def _read(ot_dir, paper_id, page_extractor=None):
        return original_read(ot_dir, paper_id, page_extractor=lambda _p: FIXTURE_PAGES)

    monkeypatch.setattr(papers_mod, "read_paper", _read)

    config = default_config()
    config.permissions.mode = "trusted"
    result = PaperFetchTool(ot, config).run(
        ToolCall(name="paper_fetch", args={"identifier": "2401.88888"})
    )
    assert result.ok is True
    assert "Reading note" in result.content
    assert is_paper_parsed(ot, paper) is True
