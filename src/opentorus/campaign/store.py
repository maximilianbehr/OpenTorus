"""Durable campaign state: the append-only event log and its derived snapshot.

Guarantees the rest of the engine relies on:

* **The log is the truth.** ``append`` writes the event line (and ``fsync``s it when
  asked) *before* it folds the event into the in-memory snapshot and rewrites
  ``snapshot.json``, so the snapshot is never ahead of the log; a crash between the
  two leaves a snapshot that ``load`` simply catches up by applying the tail.
* **Nothing is silently dropped.** A torn trailing line (crash mid-write), a corrupt
  line, a duplicate or missing ``seq``, an unknown event type, an unreadable
  ``snapshot.json`` — each becomes a :class:`Diagnostic` the caller sees; unknown
  types are preserved for the reducer, which ignores them with its own diagnostic.
* **Transitions are checked at append time.** A ``phase_entered`` / lifecycle event
  that the phase table forbids raises :class:`InvalidTransition` *before* anything is
  written; the engine turns that into ``campaign_failed`` rather than a crash.
* **Schema versions migrate.** Records with ``schema_version < SCHEMA_VERSION`` pass
  through :data:`MIGRATIONS` on read (identity for v1) so an old log stays readable.
* **Every timestamp comes from the injected clock.**
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from opentorus.atomicio import atomic_write_text
from opentorus.campaign import events as ev
from opentorus.campaign import paths, reducer
from opentorus.campaign.clock import Clock, SystemClock
from opentorus.campaign.models import (
    SCHEMA_VERSION,
    BranchRecord,
    CampaignPhase,
    CampaignRecord,
    CampaignSnapshot,
    Diagnostic,
    WorkerRole,
)
from opentorus.campaign.phases import assert_transition
from opentorus.errors import OpenTorusError

Migration = Callable[[dict[str, object]], dict[str, object]]


def _identity(record: dict[str, object]) -> dict[str, object]:
    return record


# ``MIGRATIONS[v]`` upgrades a raw event dict *to* schema version ``v``. Records
# whose ``schema_version`` is below ``SCHEMA_VERSION`` are run through every
# migration from ``their version + 1`` up to the current one, in order.
MIGRATIONS: dict[int, Migration] = {1: _identity}


def migrate_events(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Upgrade raw event dicts to :data:`SCHEMA_VERSION` (identity for current ones)."""
    out: list[dict[str, object]] = []
    for raw in records:
        record = dict(raw)
        version = record.get("schema_version", 0)
        try:
            current = int(str(version)) if version is not None else 0
        except ValueError:
            current = 0
        while current < SCHEMA_VERSION:
            current += 1
            step = MIGRATIONS.get(current, _identity)
            record = step(record)
            record["schema_version"] = current
        out.append(record)
    return out


@dataclass
class LoadedCampaign:
    record: CampaignRecord
    snapshot: CampaignSnapshot
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class ReplayReport:
    matches: bool
    diff: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    events_replayed: int = 0
    snapshot_seq: int = 0
    log_seq: int = 0


# Event types whose application moves the phase; the store validates them against
# the phase table before writing so an illegal move never reaches the log.
_LIFECYCLE_TARGETS: dict[str, CampaignPhase] = {
    ev.EventType.campaign_paused: CampaignPhase.PAUSED,
    ev.EventType.campaign_stopped: CampaignPhase.STOPPED,
    ev.EventType.campaign_completed: CampaignPhase.COMPLETED,
    ev.EventType.campaign_failed: CampaignPhase.FAILED,
}


class CampaignStore:
    """One campaign's files: create, append, load, verify."""

    def __init__(
        self,
        ot_dir: Path,
        problem_id: str,
        campaign_id: str,
        *,
        clock: Clock | None = None,
        fsync: bool = True,
        persist_every_event: bool = True,
    ) -> None:
        self.ot_dir = ot_dir
        self.problem_id = problem_id.strip().upper()
        self.campaign_id = campaign_id.strip().upper()
        self.clock: Clock = clock or SystemClock()
        self.fsync = fsync
        self.persist_every_event = persist_every_event
        self._snapshot: CampaignSnapshot | None = None
        self._record: CampaignRecord | None = None
        self._last_seq: int | None = None

    # -- paths ----------------------------------------------------------------------

    @property
    def dir(self) -> Path:
        return paths.campaign_dir(self.ot_dir, self.problem_id, self.campaign_id)

    @property
    def events_path(self) -> Path:
        return paths.events_path(self.ot_dir, self.problem_id, self.campaign_id)

    @property
    def snapshot_path(self) -> Path:
        return paths.snapshot_path(self.ot_dir, self.problem_id, self.campaign_id)

    @property
    def record_path(self) -> Path:
        return paths.campaign_yaml_path(self.ot_dir, self.problem_id, self.campaign_id)

    @property
    def progress_path(self) -> Path:
        return paths.progress_path(self.ot_dir, self.problem_id, self.campaign_id)

    @property
    def branches_dir(self) -> Path:
        return paths.branches_dir(self.ot_dir, self.problem_id, self.campaign_id)

    def exists(self) -> bool:
        return self.record_path.is_file()

    # -- create ---------------------------------------------------------------------

    def create(self, record: CampaignRecord, *, actor: str = "cli") -> ev.CampaignEvent:
        """Lay out the directory, write ``campaign.yaml``, append ``campaign_created``."""
        if self.exists() or self.events_path.exists():
            raise OpenTorusError(f"Campaign {self.campaign_id} already exists at {self.dir}.")
        if record.id != self.campaign_id or record.problem_id.upper() != self.problem_id:
            raise OpenTorusError(
                f"Record ids ({record.id}, {record.problem_id}) do not match the store "
                f"({self.campaign_id}, {self.problem_id})."
            )
        self.dir.mkdir(parents=True, exist_ok=True)
        self.branches_dir.mkdir(exist_ok=True)
        (self.branches_dir / ".gitkeep").touch()
        atomic_write_text(
            self.record_path,
            yaml.safe_dump(record.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        )
        self._record = record
        self._last_seq = 0
        self.persist_every_event = record.config_snapshot.persist_every_event
        event = ev.build_event(
            campaign_id=self.campaign_id,
            seq=1,
            timestamp=self.clock.now(),
            event_type=ev.EventType.campaign_created,
            payload=record,
            actor=actor,
        )
        self._write_line(event)
        self._last_seq = 1
        self._snapshot = reducer.empty_snapshot(event)
        self.write_snapshot()
        return event

    # -- append ---------------------------------------------------------------------

    def _write_line(self, event: ev.CampaignEvent) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        # A torn trailing line (crash mid-append) has no newline; terminate it first so
        # the new event starts a line of its own instead of extending the corrupt one.
        needs_newline = False
        if self.events_path.is_file() and self.events_path.stat().st_size > 0:
            with self.events_path.open("rb") as raw:
                raw.seek(-1, os.SEEK_END)
                needs_newline = raw.read(1) != b"\n"
        with self.events_path.open("a", encoding="utf-8") as fh:
            if needs_newline:
                fh.write("\n")
            fh.write(event.model_dump_json())
            fh.write("\n")
            fh.flush()
            if self.fsync:
                os.fsync(fh.fileno())

    def _ensure_loaded(self) -> CampaignSnapshot:
        if self._snapshot is None:
            self.load()
        assert self._snapshot is not None
        return self._snapshot

    def _check_transition(self, event_type: str, payload: dict[str, object]) -> None:
        snapshot = self._ensure_loaded()
        target: CampaignPhase | None = None
        if event_type == ev.EventType.phase_entered:
            target = CampaignPhase(str(payload.get("phase")))
        elif event_type == ev.EventType.campaign_resumed:
            target = CampaignPhase(str(payload.get("resume_phase")))
        else:
            target = _LIFECYCLE_TARGETS.get(event_type)
        if target is None:
            return
        assert_transition(snapshot.phase, target, resume_phase=snapshot.resume_phase)

    def append(
        self,
        event_type: str,
        payload: BaseModel | dict[str, object],
        *,
        actor: str = "engine",
        role: WorkerRole | None = None,
        refs: tuple[str, ...] | list[str] = (),
        causation_id: str | None = None,
        correlation_id: str | None = None,
        work_item_id: str | None = None,
        branch_id: str | None = None,
    ) -> ev.CampaignEvent:
        """Append one event: log line first, then the in-memory fold and snapshot.

        Raises :class:`InvalidTransition` (nothing written) for a phase move the table
        forbids, and ``pydantic.ValidationError`` for a payload the registry rejects.
        """
        snapshot = self._ensure_loaded()
        if snapshot.status.value in ("completed", "stopped", "failed") and event_type not in (
            ev.EventType.diagnostic_recorded,
        ):
            # Terminal campaigns take no further lifecycle or work events: the only
            # thing still worth recording is a diagnostic about the files themselves.
            raise OpenTorusError(
                f"Campaign {self.campaign_id} is {snapshot.status.value}; no further events "
                "are accepted."
            )
        raw_payload = ev.validate_payload(str(event_type), payload)
        self._check_transition(str(event_type), raw_payload)
        seq = (self._last_seq if self._last_seq is not None else snapshot.last_seq) + 1
        event = ev.build_event(
            campaign_id=self.campaign_id,
            seq=seq,
            timestamp=self.clock.now(),
            event_type=str(event_type),
            payload=raw_payload,
            actor=actor,
            role=role,
            refs=refs,
            causation_id=causation_id,
            correlation_id=correlation_id,
            work_item_id=work_item_id,
            branch_id=branch_id,
        )
        self._write_line(event)
        self._last_seq = seq
        self._snapshot = reducer.apply(snapshot, event)
        if self.persist_every_event:
            self.write_snapshot()
        return event

    # -- read -----------------------------------------------------------------------

    def read_events(self) -> tuple[list[ev.CampaignEvent], list[Diagnostic]]:
        """Every parseable event in log order, plus diagnostics for what was not.

        A partial trailing line (crash mid-append) is a ``corrupt_line`` diagnostic and
        is ignored; a corrupt line elsewhere is reported and skipped; a repeated ``seq``
        is skipped (``seq_duplicate``); a jump in ``seq`` is reported (``seq_gap``) but
        the events after it are kept.
        """
        diagnostics: list[Diagnostic] = []
        events: list[ev.CampaignEvent] = []
        if not self.events_path.is_file():
            return events, diagnostics
        raw_lines = self.events_path.read_text(encoding="utf-8").split("\n")
        # A well-formed file ends with "\n", so the split leaves one empty tail element.
        trailing_complete = raw_lines[-1] == ""
        if trailing_complete:
            raw_lines = raw_lines[:-1]
        parsed: list[dict[str, object]] = []
        line_nos: list[int] = []
        for idx, line in enumerate(raw_lines, start=1):
            text = line.strip()
            if not text:
                continue
            is_last = idx == len(raw_lines)
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                where = (
                    "trailing line is torn" if (is_last and not trailing_complete) else "corrupt"
                )
                diagnostics.append(
                    Diagnostic(
                        kind="corrupt_line",
                        message=f"events.jsonl line {idx}: {where} ({exc.msg}); ignored",
                        line_no=idx,
                    )
                )
                continue
            if not isinstance(obj, dict):
                diagnostics.append(
                    Diagnostic(
                        kind="corrupt_line",
                        message=f"events.jsonl line {idx}: not a JSON object; ignored",
                        line_no=idx,
                    )
                )
                continue
            parsed.append(obj)
            line_nos.append(idx)
        migrated = migrate_events(parsed)
        seen: set[int] = set()
        expected = 1
        for line_no, obj in zip(line_nos, migrated, strict=True):
            try:
                event = ev.parse_event(obj)
            except ev.UnknownEventError as exc:
                diagnostics.append(
                    Diagnostic(
                        kind="corrupt_line",
                        message=f"events.jsonl line {line_no}: {exc}; ignored",
                        line_no=line_no,
                    )
                )
                continue
            if event.seq in seen:
                diagnostics.append(
                    Diagnostic(
                        kind="seq_duplicate",
                        message=f"events.jsonl line {line_no}: seq {event.seq} repeated; skipped",
                        seq=event.seq,
                        line_no=line_no,
                    )
                )
                continue
            if event.seq > expected:
                diagnostics.append(
                    Diagnostic(
                        kind="seq_gap",
                        message=(
                            f"events.jsonl line {line_no}: seq jumps from {expected - 1} to "
                            f"{event.seq}"
                        ),
                        seq=event.seq,
                        line_no=line_no,
                    )
                )
            seen.add(event.seq)
            expected = event.seq + 1
            events.append(event)
        return events, diagnostics

    def _read_snapshot_file(self) -> tuple[CampaignSnapshot | None, Diagnostic | None]:
        path = self.snapshot_path
        if not path.is_file():
            return None, None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("snapshot is not a JSON object")
            snapshot = CampaignSnapshot.model_validate(data)
        except (OSError, ValueError, ValidationError) as exc:
            return None, Diagnostic(
                kind="corrupt_snapshot",
                message=f"snapshot.json unreadable ({type(exc).__name__}); replaying the log",
            )
        return snapshot, None

    def record(self) -> CampaignRecord:
        if self._record is None:
            if not self.record_path.is_file():
                raise OpenTorusError(f"No campaign.yaml for {self.campaign_id} at {self.dir}.")
            data = yaml.safe_load(self.record_path.read_text(encoding="utf-8")) or {}
            try:
                self._record = CampaignRecord.model_validate(data)
            except ValidationError as exc:
                raise OpenTorusError(
                    f"campaign.yaml for {self.campaign_id} is invalid: {exc}"
                ) from exc
            self.persist_every_event = self._record.config_snapshot.persist_every_event
        return self._record

    def load(self) -> LoadedCampaign:
        """Snapshot + tail replay; full replay when the snapshot is missing/unreadable."""
        record = self.record()
        events, diagnostics = self.read_events()
        if not events:
            raise OpenTorusError(
                f"Campaign {self.campaign_id} has no readable events in {self.events_path}."
            )
        snapshot, snap_diag = self._read_snapshot_file()
        if snap_diag is not None:
            diagnostics.append(snap_diag)
        if snapshot is not None and snapshot.last_seq > events[-1].seq:
            diagnostics.append(
                Diagnostic(
                    kind="corrupt_snapshot",
                    message=(
                        f"snapshot.json is ahead of the log (seq {snapshot.last_seq} > "
                        f"{events[-1].seq}); replaying the log"
                    ),
                )
            )
            snapshot = None
        if snapshot is None or snapshot.campaign_id != self.campaign_id:
            snapshot = reducer.reduce(events)
        else:
            for event in events:
                if event.seq > snapshot.last_seq:
                    snapshot = reducer.apply(snapshot, event)
        self._snapshot = snapshot
        self._last_seq = events[-1].seq
        return LoadedCampaign(record=record, snapshot=snapshot, diagnostics=diagnostics)

    @property
    def snapshot(self) -> CampaignSnapshot:
        return self._ensure_loaded()

    def write_snapshot(self) -> None:
        snapshot = self._ensure_loaded()
        atomic_write_text(
            self.snapshot_path,
            json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        )

    def write_branch_card(self, branch: BranchRecord) -> Path:
        """A human-readable card per branch (nothing reads it back)."""
        lines = [
            f"# {branch.branch_id} — {branch.title}",
            "",
            f"- kind: {branch.kind.value}",
            f"- root relation: {branch.root_relation.value}",
            f"- status: {branch.status.value}",
            f"- worker: {branch.assigned_worker_role.value}",
            f"- approach: {branch.approach_id or '(none)'}",
            "",
            "## Objective",
            "",
            branch.objective,
            "",
        ]
        if branch.strategy_summary:
            lines += ["## Strategy", "", branch.strategy_summary, ""]
        path = self.branches_dir / f"{branch.branch_id}.md"
        atomic_write_text(path, "\n".join(lines))
        return path

    # -- verify ---------------------------------------------------------------------

    def verify_replay(self) -> ReplayReport:
        """Does ``snapshot.json`` equal the reduction of the log prefix it claims to cover?

        The snapshot may legitimately lag the log (``persist_every_event: false``), so
        the comparison is against ``reduce(events with seq <= snapshot.last_seq)``; the
        report also says how far behind it is.
        """
        events, diagnostics = self.read_events()
        on_disk, snap_diag = self._read_snapshot_file()
        if snap_diag is not None:
            diagnostics.append(snap_diag)
        if not events:
            return ReplayReport(False, ["events.jsonl has no readable events"], diagnostics)
        if on_disk is None:
            return ReplayReport(
                False,
                ["snapshot.json missing or unreadable"],
                diagnostics,
                events_replayed=len(events),
                log_seq=events[-1].seq,
            )
        prefix = [e for e in events if e.seq <= on_disk.last_seq]
        if not prefix:
            return ReplayReport(
                False,
                [f"no events up to snapshot seq {on_disk.last_seq}"],
                diagnostics,
                events_replayed=0,
                snapshot_seq=on_disk.last_seq,
                log_seq=events[-1].seq,
            )
        replayed = reducer.reduce(prefix)
        left = replayed.model_dump(mode="json")
        right = on_disk.model_dump(mode="json")
        diff = sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))
        return ReplayReport(
            matches=not diff,
            diff=[f"{k}: replay != snapshot" for k in diff],
            diagnostics=diagnostics,
            events_replayed=len(prefix),
            snapshot_seq=on_disk.last_seq,
            log_seq=events[-1].seq,
        )


def open_campaign(ot_dir: Path, campaign_id: str, *, clock: Clock | None = None) -> CampaignStore:
    """Locate ``campaign_id`` in the workspace and return its (unloaded) store."""
    problem_id, _dir = paths.find_campaign(ot_dir, campaign_id)
    return CampaignStore(ot_dir, problem_id, campaign_id.strip().upper(), clock=clock)


__all__ = [
    "MIGRATIONS",
    "CampaignStore",
    "LoadedCampaign",
    "ReplayReport",
    "migrate_events",
    "open_campaign",
]
