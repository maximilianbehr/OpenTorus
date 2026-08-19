"""Durability contract of the campaign store: log first, snapshot never ahead, replay,
tolerant reads, migration hook."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentorus.campaign import events as ev
from opentorus.campaign import reducer
from opentorus.campaign.clock import StepClock
from opentorus.campaign.ids import event_id, next_campaign_id
from opentorus.campaign.models import (
    ArtifactRef,
    CampaignConfigSnapshot,
    CampaignMode,
    CampaignPhase,
    CampaignRecord,
)
from opentorus.campaign.paths import list_campaigns
from opentorus.campaign.store import MIGRATIONS, CampaignStore, migrate_events, open_campaign
from opentorus.errors import OpenTorusError
from opentorus.research.dossier.store import create_dossier
from opentorus.workspace import init_workspace, workspace_dir


def _record(cid: str, pid: str, clock: StepClock) -> CampaignRecord:
    return CampaignRecord(
        id=cid,
        problem_id=pid,
        mode=CampaignMode.exploration,
        created_at=clock.now(),
        config_snapshot=CampaignConfigSnapshot(mode=CampaignMode.exploration, max_steps=5),
    )


def _store(tmp_path: Path, *, clock: StepClock | None = None) -> tuple[Path, CampaignStore]:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    create_dossier(ot, "For every n, P(n).")
    clock = clock or StepClock()
    cid = next_campaign_id(ot)
    store = CampaignStore(ot, "PROBLEM-0001", cid, clock=clock)
    store.create(_record(cid, "PROBLEM-0001", clock))
    return ot, store


def _drive(store: CampaignStore) -> None:
    """A few realistic events: start, enter INGEST, an artifact ref, enter NORMALIZE."""
    cfg = store.record().config_snapshot
    store.append(
        ev.EventType.campaign_started,
        ev.CampaignStartedPayload(
            problem_id="PROBLEM-0001", mode=CampaignMode.exploration, config_snapshot=cfg
        ),
    )
    store.append(
        ev.EventType.phase_entered,
        ev.PhaseEnteredPayload(phase=CampaignPhase.INGEST, from_phase=CampaignPhase.CREATED),
    )
    store.append(
        ev.EventType.artifact_created,
        ArtifactRef(artifact_id="PROBLEM-0001", kind="problem_statement"),
    )
    store.append(
        ev.EventType.phase_entered,
        ev.PhaseEnteredPayload(phase=CampaignPhase.NORMALIZE, from_phase=CampaignPhase.INGEST),
    )


def test_campaign_ids_are_workspace_unique_across_dossiers(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    create_dossier(ot, "For every n, P(n).")
    create_dossier(ot, "For every m, Q(m).")
    clock = StepClock()
    first = next_campaign_id(ot)
    assert first == "CAMPAIGN-0001"
    CampaignStore(ot, "PROBLEM-0001", first, clock=clock).create(
        _record(first, "PROBLEM-0001", clock)
    )
    second = next_campaign_id(ot)
    assert second == "CAMPAIGN-0002"
    CampaignStore(ot, "PROBLEM-0002", second, clock=clock).create(
        _record(second, "PROBLEM-0002", clock)
    )
    assert next_campaign_id(ot) == "CAMPAIGN-0003"
    assert list_campaigns(ot) == [
        ("PROBLEM-0001", "CAMPAIGN-0001"),
        ("PROBLEM-0002", "CAMPAIGN-0002"),
    ]
    assert list_campaigns(ot, problem_id="PROBLEM-0002") == [("PROBLEM-0002", "CAMPAIGN-0002")]
    pid, _dir = __import__("opentorus.campaign.paths", fromlist=["find_campaign"]).find_campaign(
        ot, "campaign-0002"
    )
    assert pid == "PROBLEM-0002"


def test_event_ids_derive_from_seq_and_layout_is_created(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    assert store.record_path.is_file()
    assert store.events_path.is_file()
    assert store.snapshot_path.is_file()
    assert store.branches_dir.is_dir()
    events, diags = store.read_events()
    assert not diags
    assert [e.event_id for e in events] == ["EVT-000001"]
    assert event_id(42) == "EVT-000042"
    _drive(store)
    events, _ = store.read_events()
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert events[-1].event_id == "EVT-000005"


def test_snapshot_is_never_ahead_of_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    # Simulate a crash between the log write and the snapshot write: the snapshot on
    # disk lags the log, and load() catches up by applying the tail.
    monkeypatch.setattr(store, "write_snapshot", lambda: None)
    store.append(
        ev.EventType.phase_entered,
        ev.PhaseEnteredPayload(
            phase=CampaignPhase.MAP_LITERATURE, from_phase=CampaignPhase.NORMALIZE
        ),
    )
    on_disk = json.loads(store.snapshot_path.read_text())
    assert on_disk["last_seq"] == 5
    events, _ = store.read_events()
    assert events[-1].seq == 6
    fresh = CampaignStore(store.ot_dir, "PROBLEM-0001", store.campaign_id, clock=StepClock())
    loaded = fresh.load()
    assert loaded.snapshot.last_seq == 6
    assert loaded.snapshot.phase is CampaignPhase.MAP_LITERATURE
    assert not loaded.diagnostics
    # verify_replay compares the prefix the snapshot claims to cover.
    report = fresh.verify_replay()
    assert report.matches
    assert report.snapshot_seq == 5 and report.log_seq == 6


def test_reduce_events_equals_snapshot_after_run(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    events, _ = store.read_events()
    replayed = reducer.reduce(events)
    on_disk = json.loads(store.snapshot_path.read_text())
    assert replayed.model_dump(mode="json") == on_disk
    assert store.verify_replay().matches


def test_torn_trailing_line_is_a_diagnostic_and_state_is_the_valid_prefix(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    events_before, _ = store.read_events()
    text = store.events_path.read_text()
    lines = text.split("\n")
    # Truncate the last event mid-JSON (no trailing newline): a crash mid-append.
    torn = lines[-2][: len(lines[-2]) // 2]
    store.events_path.write_text("\n".join(lines[:-2]) + "\n" + torn)
    fresh = CampaignStore(store.ot_dir, "PROBLEM-0001", store.campaign_id, clock=StepClock())
    events, diags = fresh.read_events()
    assert [d.kind for d in diags] == ["corrupt_line"]
    assert "torn" in diags[0].message
    assert [e.seq for e in events] == [e.seq for e in events_before[:-1]]
    loaded = fresh.load()
    assert loaded.snapshot.model_dump(mode="json") == reducer.reduce(events).model_dump(mode="json")
    assert [d.kind for d in loaded.diagnostics] == ["corrupt_snapshot", "corrupt_line"] or [
        d.kind for d in loaded.diagnostics
    ] == ["corrupt_line", "corrupt_snapshot"]
    # The next append continues from the last *valid* seq — no gap, no duplicate.
    fresh.append(
        ev.EventType.phase_entered,
        ev.PhaseEnteredPayload(phase=CampaignPhase.NORMALIZE, from_phase=CampaignPhase.INGEST),
    )
    events2, diags2 = fresh.read_events()
    assert [d.kind for d in diags2] == ["corrupt_line"]
    assert events2[-1].seq == events[-1].seq + 1


def test_torn_snapshot_triggers_full_replay_with_diagnostic(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    good = json.loads(store.snapshot_path.read_text())
    store.snapshot_path.write_text(store.snapshot_path.read_text()[:40])
    fresh = CampaignStore(store.ot_dir, "PROBLEM-0001", store.campaign_id, clock=StepClock())
    loaded = fresh.load()
    assert [d.kind for d in loaded.diagnostics] == ["corrupt_snapshot"]
    assert loaded.snapshot.model_dump(mode="json") == good
    report = fresh.verify_replay()
    assert not report.matches
    assert any("snapshot.json" in line for line in report.diff)
    # A rewrite repairs it.
    fresh.write_snapshot()
    assert fresh.verify_replay().matches


def test_duplicate_and_gap_seq_are_diagnosed(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    lines = store.events_path.read_text().rstrip("\n").split("\n")
    dup = json.loads(lines[2])
    gap = json.loads(lines[4])
    gap["seq"] = 9
    gap["event_id"] = "EVT-000009"
    store.events_path.write_text(
        "\n".join([*lines[:3], json.dumps(dup), lines[3], json.dumps(gap)]) + "\n"
    )
    fresh = CampaignStore(store.ot_dir, "PROBLEM-0001", store.campaign_id, clock=StepClock())
    events, diags = fresh.read_events()
    assert sorted(d.kind for d in diags) == ["seq_duplicate", "seq_gap"]
    assert [e.seq for e in events] == [1, 2, 3, 4, 9]
    loaded = fresh.load()
    assert loaded.snapshot.last_seq == 9


def test_unknown_event_type_is_preserved_and_ignored(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    unknown = {
        "event_id": "EVT-000006",
        "campaign_id": store.campaign_id,
        "seq": 6,
        "schema_version": 1,
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "type": "from_the_future",
        "payload": {"x": 1},
    }
    with store.events_path.open("a") as fh:
        fh.write(json.dumps(unknown) + "\n")
    fresh = CampaignStore(store.ot_dir, "PROBLEM-0001", store.campaign_id, clock=StepClock())
    events, diags = fresh.read_events()
    assert not diags
    assert events[-1].type == "from_the_future"
    assert events[-1].payload == {"x": 1}
    loaded = fresh.load()
    assert loaded.snapshot.phase is CampaignPhase.NORMALIZE
    assert [d.kind for d in loaded.snapshot.diagnostics] == ["unknown_event_type"]
    assert loaded.snapshot.last_seq == 6


def test_unknown_fields_survive_a_round_trip(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    lines = store.events_path.read_text().rstrip("\n").split("\n")
    obj = json.loads(lines[-1])
    obj["novel_envelope_key"] = {"nested": True}
    obj["payload"]["novel_payload_key"] = "kept"
    lines[-1] = json.dumps(obj)
    store.events_path.write_text("\n".join(lines) + "\n")
    fresh = CampaignStore(store.ot_dir, "PROBLEM-0001", store.campaign_id, clock=StepClock())
    events, diags = fresh.read_events()
    assert not diags
    dumped = events[-1].model_dump()
    assert dumped["novel_envelope_key"] == {"nested": True}
    assert events[-1].payload["novel_payload_key"] == "kept"
    # and the store can still fold it
    assert fresh.load().snapshot.phase is CampaignPhase.NORMALIZE


def test_migration_hook_runs_for_older_schema_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def _spy(record: dict[str, object]) -> dict[str, object]:
        calls.append(int(str(record["seq"])))
        return record

    monkeypatch.setitem(MIGRATIONS, 1, _spy)
    _ot, store = _store(tmp_path)
    _drive(store)
    lines = store.events_path.read_text().rstrip("\n").split("\n")
    obj = json.loads(lines[-1])
    obj["schema_version"] = 0
    lines[-1] = json.dumps(obj)
    store.events_path.write_text("\n".join(lines) + "\n")
    fresh = CampaignStore(store.ot_dir, "PROBLEM-0001", store.campaign_id, clock=StepClock())
    events, _ = fresh.read_events()
    assert calls == [events[-1].seq]
    assert events[-1].schema_version == 1
    # direct API
    out = migrate_events([{"seq": 1, "schema_version": 0}, {"seq": 2, "schema_version": 1}])
    assert [r["schema_version"] for r in out] == [1, 1]
    assert calls == [events[-1].seq, 1]


def test_invalid_transition_is_refused_at_append_time_and_nothing_written(tmp_path: Path) -> None:
    from opentorus.agent.control.phase_machine import InvalidTransition

    _ot, store = _store(tmp_path)
    _drive(store)
    before = store.events_path.read_text()
    with pytest.raises(InvalidTransition):
        store.append(
            ev.EventType.phase_entered,
            ev.PhaseEnteredPayload(phase=CampaignPhase.EXECUTE, from_phase=CampaignPhase.NORMALIZE),
        )
    assert store.events_path.read_text() == before


def test_invalid_transition_in_an_old_log_becomes_a_replay_diagnostic(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    bad = {
        "event_id": "EVT-000006",
        "campaign_id": store.campaign_id,
        "seq": 6,
        "schema_version": 1,
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "type": "phase_entered",
        "payload": {"phase": "execute", "from_phase": "normalize", "reason": ""},
    }
    with store.events_path.open("a") as fh:
        fh.write(json.dumps(bad) + "\n")
    events, _ = CampaignStore(store.ot_dir, "PROBLEM-0001", store.campaign_id).read_events()
    snap = reducer.reduce(events)
    assert snap.phase is CampaignPhase.NORMALIZE
    assert [d.kind for d in snap.diagnostics] == ["invalid_transition"]


def test_reducer_is_pure_and_input_is_not_mutated(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    events, _ = store.read_events()
    base = reducer.empty_snapshot(events[0])
    frozen = base.model_dump(mode="json")
    started = ev.build_event(
        campaign_id=store.campaign_id,
        seq=2,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        event_type=ev.EventType.campaign_started,
        payload=ev.CampaignStartedPayload(
            problem_id="PROBLEM-0001",
            mode=CampaignMode.exploration,
            config_snapshot=CampaignConfigSnapshot(),
        ),
    )
    new = reducer.apply(base, started)
    assert base.model_dump(mode="json") == frozen
    assert new.status.value == "running" and new.last_seq == 2
    # duplicates are skipped with a diagnostic
    again = reducer.apply(new, started)
    assert again.last_seq == 2
    assert [d.kind for d in again.diagnostics] == ["seq_duplicate"]


def test_open_campaign_names_known_ids_when_missing(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    with pytest.raises(OpenTorusError, match="CAMPAIGN-0001"):
        open_campaign(store.ot_dir, "CAMPAIGN-0099")
    with pytest.raises(OpenTorusError, match="not a campaign id"):
        open_campaign(store.ot_dir, "PROBLEM-0001")


def test_terminal_campaign_accepts_no_further_events(tmp_path: Path) -> None:
    _ot, store = _store(tmp_path)
    _drive(store)
    store.append(ev.EventType.campaign_stopped, ev.CampaignStoppedPayload(reason="done"))
    with pytest.raises(OpenTorusError, match="stopped"):
        store.append(
            ev.EventType.phase_entered,
            ev.PhaseEnteredPayload(phase=CampaignPhase.INGEST, from_phase=CampaignPhase.CREATED),
        )
