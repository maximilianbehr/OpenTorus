"""Event registry and payload contracts of the campaign layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args

import pytest

from opentorus.campaign import events as ev
from opentorus.campaign.models import (
    BranchKind,
    BranchRecord,
    BranchStatus,
    CampaignMode,
    CampaignPhase,
    ClosureMode,
    RootRelation,
    ScoreBreakdown,
    WorkerRole,
)
from opentorus.config import CampaignMode as ConfigCampaignMode
from opentorus.research.theorems.models import ROOT_RELATIONS

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def test_event_registry_covers_assignment_types() -> None:
    assert set(ev.EVENT_PAYLOADS) >= ev.ASSIGNMENT_EVENT_TYPES
    # Every registered type is an EventType member and vice versa.
    assert set(ev.EVENT_PAYLOADS) == {t.value for t in ev.EventType}


def test_assignment_types_are_exactly_the_named_ones() -> None:
    assert len(ev.ASSIGNMENT_EVENT_TYPES) == 29
    for name in (
        "campaign_created",
        "worker_failed",
        "routing_decision_recorded",
        "campaign_completed",
    ):
        assert name in ev.ASSIGNMENT_EVENT_TYPES


def test_root_relation_values_equal_theorems_root_relations() -> None:
    assert tuple(r.value for r in RootRelation) == ROOT_RELATIONS


def test_campaign_mode_values_equal_config_literal() -> None:
    assert {m.value for m in CampaignMode} == set(get_args(ConfigCampaignMode))


def test_campaign_phase_has_the_sixteen_assignment_values() -> None:
    assert [p.value for p in CampaignPhase] == [
        "created",
        "ingest",
        "normalize",
        "map-literature",
        "generate-portfolio",
        "schedule",
        "execute",
        "critique",
        "verify",
        "update-graph",
        "reallocate",
        "synthesize",
        "completed",
        "paused",
        "stopped",
        "failed",
    ]


def test_enum_cardinalities() -> None:
    assert len(BranchKind) == 9
    assert len(WorkerRole) == 10
    assert len(ClosureMode) == 7
    assert len(BranchStatus) == 6


def test_build_event_fills_envelope_and_validates_payload() -> None:
    event = ev.build_event(
        campaign_id="CAMPAIGN-0001",
        seq=7,
        timestamp=_TS,
        event_type=ev.EventType.phase_entered,
        payload=ev.PhaseEnteredPayload(
            phase=CampaignPhase.INGEST, from_phase=CampaignPhase.CREATED
        ),
        actor="engine",
    )
    assert event.event_id == "EVT-000007"
    assert event.payload == {"phase": "ingest", "from_phase": "created", "reason": ""}
    assert event.schema_version == 1


def test_build_event_rejects_invalid_payload_for_known_type() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ev.build_event(
            campaign_id="CAMPAIGN-0001",
            seq=1,
            timestamp=_TS,
            event_type=ev.EventType.branch_activated,
            payload={"priority": "not-a-number"},
        )


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (
            ev.EventType.branch_proposed,
            BranchRecord(
                branch_id="BRANCH-0001",
                campaign_id="CAMPAIGN-0001",
                title="t",
                kind=BranchKind.literature,
                objective="o",
                root_relation=RootRelation.supporting,
            ),
        ),
        (
            ev.EventType.work_item_scheduled,
            ev.WorkItemScheduledPayload(
                work_item_id="WI-0001", score=ScoreBreakdown(total=1.5, tie_break="BRANCH-0001")
            ),
        ),
        (
            ev.EventType.budget_consumed,
            ev.BudgetConsumedPayload(scope="work_item", ref="WI-0001", steps=3, wall_seconds=1.5),
        ),
        (
            ev.EventType.campaign_paused,
            ev.CampaignPausedPayload(reason="x", resume_phase=CampaignPhase.SCHEDULE),
        ),
        (
            ev.EventType.obligation_closed,
            ev.ObligationClosedPayload(
                obligation_id="OBL-0001",
                artifact_id="PROOF-0001",
                closure_mode=ClosureMode.formal_proof,
            ),
        ),
    ],
)
def test_payload_round_trips_through_json(event_type: str, payload: object) -> None:
    event = ev.build_event(
        campaign_id="CAMPAIGN-0001",
        seq=1,
        timestamp=_TS,
        event_type=event_type,
        payload=payload,  # type: ignore[arg-type]
    )
    raw = event.model_dump_json()
    parsed = ev.parse_event(__import__("json").loads(raw))
    assert parsed.type == event_type
    assert parsed.typed_payload() == ev.EVENT_PAYLOADS[event_type].model_validate(event.payload)


def test_parse_event_keeps_unknown_types_and_flags_them() -> None:
    raw = {
        "event_id": "EVT-000003",
        "campaign_id": "CAMPAIGN-0001",
        "seq": 3,
        "schema_version": 1,
        "timestamp": _TS.isoformat(),
        "type": "future_event_type",
        "payload": {"anything": [1, 2, 3]},
    }
    event = ev.parse_event(raw)
    assert event.type == "future_event_type"
    assert event.payload == {"anything": [1, 2, 3]}
    assert not ev.is_known_type(event)
    assert event.typed_payload() is None


def test_parse_event_tolerates_unknown_envelope_fields() -> None:
    raw = {
        "event_id": "EVT-000001",
        "campaign_id": "CAMPAIGN-0001",
        "seq": 1,
        "timestamp": _TS.isoformat(),
        "type": "phase_completed",
        "payload": {"phase": "ingest", "outcome": "ok", "next_phase": "normalize", "extra_key": 1},
        "brand_new_envelope_field": "kept",
    }
    event = ev.parse_event(raw)
    assert event.model_dump()["brand_new_envelope_field"] == "kept"
    assert event.payload["extra_key"] == 1


def test_parse_event_rejects_non_events() -> None:
    with pytest.raises(ev.UnknownEventError):
        ev.parse_event({"not": "an event"})
