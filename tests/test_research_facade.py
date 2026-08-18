"""The research façade: ``run_research`` unchanged by default, opt-in campaign
recording, and the legacy importer (originals untouched, provenance recorded)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from opentorus.agent.research_loop import (
    list_states,
    load_state,
    load_state_by_slug,
    run_research,
)
from opentorus.campaign.clock import StepClock
from opentorus.campaign.importer import import_research, import_research_state
from opentorus.campaign.models import BranchKind, CampaignPhase, CampaignStatus, RootRelation
from opentorus.campaign.paths import campaigns_dir, list_campaigns
from opentorus.campaign.store import open_campaign
from opentorus.config import default_config
from opentorus.errors import OpenTorusError
from opentorus.providers.mock_provider import MockProvider
from opentorus.research.dossier import store as dstore
from opentorus.research.dossier.store import create_dossier
from opentorus.research.journal import list_entries
from opentorus.workspace import init_workspace, workspace_dir

FIXTURE = Path(__file__).parent / "fixtures" / "legacy_research"


def _setup(tmp_path: Path, *, dossier: bool = True) -> tuple[Path, Path, str | None]:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    pid = create_dossier(ot, "For every n >= 1, P(n) holds.").id if dossier else None
    return tmp_path, ot, pid


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_plain_research_creates_no_campaign_dir(tmp_path: Path) -> None:
    root, ot, pid = _setup(tmp_path)
    assert pid is not None
    outcome = run_research(
        root, ot, MockProvider(), default_config(), "Is P bounded?", max_iterations=2
    )
    assert outcome.iterations_run == 2
    assert not campaigns_dir(ot, pid).exists()
    assert list_campaigns(ot) == []
    assert load_state(ot, "Is P bounded?") is not None
    assert load_state_by_slug(ot, "is-p-bounded") is not None
    assert [s.slug for s in list_states(ot)] == ["is-p-bounded"]
    assert len(list_entries(ot)) == 2
    # the same holds when asked to record but nothing is attributed
    root2, ot2, _ = _setup(tmp_path / "unattributed", dossier=False)
    run_research(
        root2, ot2, MockProvider(), default_config(), "Q?", max_iterations=1, record_campaign=True
    )
    assert list_campaigns(ot2) == []


def test_record_campaign_mirrors_the_run_and_leaves_research_files_untouched(
    tmp_path: Path,
) -> None:
    root, ot, pid = _setup(tmp_path)
    assert pid is not None
    outcome = run_research(
        root,
        ot,
        MockProvider(),
        default_config(),
        "Is P bounded?",
        max_iterations=2,
        record_campaign=True,
    )
    state_path = ot / "research" / f"{outcome.slug}.json"
    journal_path = ot / "journal" / "journal.jsonl"
    state = json.loads(state_path.read_text())
    assert state["completed_iterations"] == 2 and state["status"] == "completed"
    assert len(list_entries(ot, outcome.slug)) == 2
    assert outcome.progress_path and (ot / outcome.progress_path).is_file()
    found = list_campaigns(ot, problem_id=pid)
    assert len(found) == 1
    store = open_campaign(ot, found[0][1])
    loaded = store.load()
    assert not loaded.diagnostics
    assert loaded.record.imported_from == f"research:{outcome.slug}"
    assert loaded.record.mode.value == "exploration"
    snap = loaded.snapshot
    assert snap.status is CampaignStatus.completed
    assert snap.completion_reason is not None
    assert snap.completion_reason.startswith("research run stopped: iteration cap reached")
    branches = list(snap.branches.values())
    assert len(branches) == 1
    branch = branches[0]
    assert branch.kind is BranchKind.numerical and branch.root_relation is RootRelation.supporting
    assert branch.title.startswith("Autonomous research: Is P bounded?")
    assert len(snap.work_items) == 2
    types = [e.type for e in store.read_events()[0]]
    for needed in (
        "work_item_created",
        "work_item_scheduled",
        "worker_started",
        "worker_completed",
        "artifact_created",
        "campaign_completed",
    ):
        assert types.count(needed) >= 2 or needed == "campaign_completed", needed
    ids = {r.artifact_id for r in snap.artifact_refs}
    assert {"EXP-0001", "EXP-0002", "EVIDENCE-0001", "CLAIM-0001"} <= ids
    assert store.verify_replay().matches
    # the research state, journal, progress note and checkpoints are exactly what a
    # non-recorded run writes: same state file content, same journal shape
    root2, ot2, _ = _setup(tmp_path / "plain")
    plain = run_research(
        root2, ot2, MockProvider(), default_config(), "Is P bounded?", max_iterations=2
    )
    assert json.loads((ot2 / "research" / f"{plain.slug}.json").read_text()) == state
    plain_entries = list_entries(ot2, plain.slug)
    entries = list_entries(ot, outcome.slug)
    assert [(e.iteration, e.actions, e.evidence_ids, e.claim_id) for e in entries] == [
        (e.iteration, e.actions, e.evidence_ids, e.claim_id) for e in plain_entries
    ]
    assert journal_path.is_file()
    # config opt-in works the same way, and a resumed run gets a further campaign
    config = default_config()
    config.campaign.record_research = True
    run_research(root, ot, MockProvider(), config, "Is P bounded?", max_iterations=3)
    assert len(list_campaigns(ot, problem_id=pid)) == 2
    assert load_state(ot, "Is P bounded?").completed_iterations == 3  # type: ignore[union-attr]


def _stage_fixture(tmp_path: Path) -> tuple[Path, Path]:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    for path in FIXTURE.rglob("*"):
        if path.is_file() and path.name != "README.md":
            target = ot / path.relative_to(FIXTURE)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return tmp_path, ot


def test_importer_round_trip_leaves_originals_untouched_and_refuses_twice(tmp_path: Path) -> None:
    _root, ot = _stage_fixture(tmp_path)
    slug = "is-a-n-prime-for-every-n"
    sources = [
        ot / "research" / f"{slug}.json",
        ot / "journal" / "journal.jsonl",
        ot / "research" / slug / "progress.md",
    ]
    before = {p: _sha(p) for p in sources}
    assert load_state_by_slug(ot, slug) is not None
    report = import_research(ot, slug=slug, clock=StepClock())
    assert report.campaign_id == "CAMPAIGN-0001" and report.problem_id == "PROBLEM-0001"
    assert report.entries == 2 and report.completed
    assert {p: _sha(p) for p in sources} == before  # originals byte-identical
    store = open_campaign(ot, report.campaign_id)
    loaded = store.load()
    assert not loaded.diagnostics or all(d.kind == "migration" for d in loaded.diagnostics)
    record = loaded.record
    assert record.imported_from == f"research:{slug}"
    assert record.created_by == "importer"
    assert record.migration_provenance is not None
    assert record.migration_provenance["importer_version"] == "1"
    assert set(record.migration_provenance["source_paths"]) == {  # type: ignore[arg-type]
        f"research/{slug}.json",
        "journal/journal.jsonl",
        f"research/{slug}/progress.md",
    }
    events, _ = store.read_events()
    assert events[0].type == "campaign_created"
    assert events[1].type == "migration_recorded"
    payload = events[1].payload
    assert payload["importer_version"] == "1"
    assert sorted(payload["sha256s"]) == sorted(before.values())  # type: ignore[arg-type]
    assert payload["imported_at"]
    snap = loaded.snapshot
    assert snap.status is CampaignStatus.completed
    assert snap.completion_reason is not None and "iteration cap reached" in snap.completion_reason
    assert len(snap.work_items) == 2
    assert [wi.role.value for wi in snap.work_items.values()] == ["numerical-experimenter"] * 2
    ids = {r.artifact_id for r in snap.artifact_refs}
    assert {"EXP-0001", "EXP-0002", "EVIDENCE-0001", "EVIDENCE-0002", "CLAIM-0001"} <= ids
    assert [d.kind for d in snap.diagnostics] == ["migration"]
    assert store.verify_replay().matches
    # the dossier was not touched either
    assert dstore.list_status_changes(ot, "PROBLEM-0001") == []
    # a second import is refused; --force imports again as a further campaign
    with pytest.raises(OpenTorusError, match="already imported"):
        import_research_state(ot, slug=slug, clock=StepClock())
    again = import_research_state(
        ot, question="Is a(n) prime for every n?", clock=StepClock(), force=True
    )
    assert again.id == "CAMPAIGN-0002" and again.imported_from == f"research:{slug}"
    assert {p: _sha(p) for p in sources} == before
    # unknown investigations are refused with the known slugs
    with pytest.raises(OpenTorusError, match="Known investigations"):
        import_research_state(ot, slug="nope", clock=StepClock())
    with pytest.raises(OpenTorusError, match="QUESTION or --slug"):
        import_research_state(ot, clock=StepClock())


def test_importer_leaves_a_running_investigation_resumable(tmp_path: Path) -> None:
    _root, ot = _stage_fixture(tmp_path)
    slug = "is-a-n-prime-for-every-n"
    state_path = ot / "research" / f"{slug}.json"
    data = json.loads(state_path.read_text())
    data["status"] = "running"
    data["stopped_reason"] = None
    state_path.write_text(json.dumps(data, indent=2))
    report = import_research(ot, slug=slug, clock=StepClock())
    assert not report.completed
    snap = open_campaign(ot, report.campaign_id).load().snapshot
    assert snap.status is CampaignStatus.running
    assert snap.phase is CampaignPhase.SCHEDULE  # resumable, non-terminal
    assert len(snap.work_items) == 2


def test_import_research_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    _stage_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["campaign", "import-research", "--slug", "is-a-n-prime-for-every-n"])
    assert res.exit_code == 0, res.output
    assert res.output.splitlines()[0].strip() == "CAMPAIGN-0001"
    flat = " ".join(res.output.split())  # Rich wraps long lines
    assert "2 journal entries" in flat and "not modified" in flat
    twice = runner.invoke(app, ["campaign", "import-research", "Is a(n) prime for every n?"])
    assert twice.exit_code == 2 and "already imported" in twice.output
    forced = runner.invoke(
        app, ["campaign", "import-research", "Is a(n) prime for every n?", "--force"]
    )
    assert forced.exit_code == 0 and "CAMPAIGN-0002" in forced.output
    missing = runner.invoke(app, ["campaign", "import-research", "--slug", "nothing-here"])
    assert missing.exit_code == 1 and "Known investigations" in missing.output
    status = runner.invoke(app, ["campaign", "status", "CAMPAIGN-0001", "--json"])
    assert status.exit_code == 0 and json.loads(status.output)["status"] == "completed"
    research = runner.invoke(app, ["research", "--help"])
    assert research.exit_code == 0 and "--campaign" in research.output
