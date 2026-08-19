# Campaign persistence

How a campaign is stored, what an event looks like, how the snapshot is derived
from the log, and how a legacy `research` run becomes a campaign. Modules:
`opentorus.campaign.paths`, `events`, `reducer`, `store`, `ids`, `clock`,
`research_bridge`, `importer`.

The design rule, from [adr/0001-campaign-engine.md](adr/0001-campaign-engine.md):
**the event log is the truth**. `snapshot.json` is only ever a cache of the
reduction of that log; it holds orchestration state and artifact *references*,
never a claim status or the problem's mathematical status, so the campaign layer
cannot become a second source of truth for what is proved. A campaign can
finish without solving the problem, and nothing in these files can say
otherwise.

## Layout

A campaign lives under its dossier, so a dossier export or pack carries its
campaigns. `campaigns/` is on the dossier's write-protected list: the agent's
file tools cannot edit these files.

```
.opentorus/problems/PROBLEM-0001/campaigns/CAMPAIGN-0001/
  campaign.yaml     the immutable CampaignRecord: id, problem_id, mode,
                    schema_version, created_at, statement_sha256, the frozen
                    config_snapshot (every budget as started, 0 = unlimited),
                    imported_from / migration_provenance, primary_claim_id
  events.jsonl      the append-only typed event log -- the source of truth
  snapshot.json     the reducer's output, atomically rewritten, never ahead of
                    the log
  progress.md       a human-readable summary (orchestration state only; the
                    problem status is printed separately, from the dossier)
  branches/         one Markdown card per branch, for humans; nothing reads them
```

`CAMPAIGN-NNNN` ids are **workspace-unique** (`ids.next_campaign_id` scans every
`campaigns/` directory under every problem with `jsonl.next_id`), so `campaign
status CAMPAIGN-0002` needs no problem argument and two dossiers never share an
id. An empty `CAMPAIGN-*` directory (an aborted create) is ignored and its id
reused.

## The event envelope

One line of `events.jsonl` is a `CampaignEvent`:

| field | meaning |
|---|---|
| `event_id` | `EVT-000001` -- derived from `seq` (`ids.event_id`), so the id *is* the position |
| `campaign_id`, `seq` | the campaign; the 1-based position in the log |
| `schema_version` | `1` today (`campaign.models.SCHEMA_VERSION`) |
| `timestamp` | from the injected clock, never `datetime.now` inline |
| `type` | one of the types below (unknown types are preserved, see "Tolerance") |
| `actor` | `cli`, `engine`, or a worker |
| `role` | the `WorkerRole` when a worker caused the event |
| `refs` | artifact / campaign ids the event is about |
| `payload` | a dict validated against the model registered for `type` in `events.EVENT_PAYLOADS` |
| `causation_id`, `correlation_id` | the event that triggered this one; the work item that groups it -- so a reader can follow a chain without the engine |
| `work_item_id`, `branch_id` | denormalised for grep |

Every persisted model (envelope, payloads, snapshot, records) uses
`extra="allow"`: a field a newer build added survives a round trip through an
older one.

### Event types

The assignment's twenty-nine types (pinned by `tests/test_campaign_events.py`:
`set(EVENT_PAYLOADS) >= ASSIGNMENT_EVENT_TYPES`) and the extras the engine needs to
be honest about failures, obligations, coverage and migrations. "Payload" names
the registered model.

Assignment types:

| type | payload | recorded when |
|---|---|---|
| `campaign_created` | `CampaignRecord` | the store lays out the directory (always `seq` 1) |
| `campaign_started` | problem, mode, `config_snapshot` | the first time the phase loop actually runs (a `--no-run` campaign reads `created` until then) |
| `phase_entered` | phase, `from_phase`, reason | every transition (checked against the phase table before writing) |
| `phase_completed` | phase, outcome, `next_phase` | the phase handler's one-line outcome |
| `branch_proposed` | `BranchRecord` | GENERATE_PORTFOLIO (also for later duplicates, kept as `rejected`) |
| `branch_rejected` | `branch_id`, `reason_code` (`REPEATED_STRATEGY`, `PORTFOLIO_CAP`), `duplicate_of` | de-duplication and the cap |
| `branch_activated` | `branch_id`, priority, slot | activation of a proposed branch |
| `branch_suspended` | `branch_id`, `reason_code`, `reactivation_conditions` | a refused retry; repeated identical failures |
| `branch_reactivated` | `branch_id`, `condition_met`, observed | a recorded condition was met |
| `work_item_created` | `WorkItem` (id, branch, role, task class, objective, session id, budget) | SCHEDULE |
| `work_item_scheduled` | `work_item_id`, the full `ScoreBreakdown`, `claimed_by` | SCHEDULE |
| `worker_started` | `work_item_id`, role, `session_id`, `WorkBudget` | EXECUTE |
| `worker_completed` | `work_item_id`, status, usage, artifact ids, notes | EXECUTE |
| `worker_failed` | `work_item_id`, `error_category`, message, `failure_signature_id` | EXECUTE |
| `artifact_created` | `ArtifactRef` (artifact id, kind, branch, work item, role, digest) | any phase that produced or pinned a dossier / workspace artifact |
| `proof_node_created` | `CampaignNodeState` | UPDATE_GRAPH |
| `proof_node_updated` | `node_id`, changes | UPDATE_GRAPH |
| `theorem_reference_created` | `theorem_reference_id`, paper, review status | a worker created a THMREF |
| `review_requested` | `target_id`, kind | CRITIQUE |
| `review_recorded` | `ReviewRef` (review id, target, verdict) | CRITIQUE |
| `verification_requested` | `artifact_id`, backend | a worker submitted to a verifier |
| `verification_recorded` | `VerificationRef` (artifact, backend, accepted, inconclusive) | the verifier ledger answered |
| `budget_consumed` | scope (`campaign` / `branch` / `work_item` / `model_invocation` / `tool_execution` / `experiment`), ref, steps, tokens, cost, wall seconds | after every work item and strategist call |
| `budget_exhausted` | axis, used, limit, scope | once per axis, in REALLOCATE (or the governance check before a work item) |
| `routing_decision_recorded` | `RouteSummary` (decision id, task class, selected profile, provider, actual model) | a worker's pool lease (the full record is in `usage/routing.jsonl`) |
| `campaign_paused` | reason, `resume_phase` | `campaign pause`, budget exhaustion, Ctrl-C (`interrupted`), a stop flag |
| `campaign_resumed` | `from_phase` (PAUSED), `resume_phase`, note | `campaign resume` |
| `campaign_stopped` | reason | `campaign stop` (terminal) |
| `campaign_completed` | reason (with the problem status per dossier), `mode_criterion` | SYNTHESIZE (terminal) |

Extras:

| type | payload | recorded when |
|---|---|---|
| `branch_completed` | `branch_id`, reason | a worker returned `branch_done` |
| `branch_exhausted` | `branch_id`, reason | the branch spent `branch_step_budget` |
| `branch_updated` | `branch_id`, changes | a field changed on an existing branch (e.g. the target claim a worker picked) |
| `obligation_created` | `Obligation` | a prover's gap became an obligation |
| `obligation_updated` | `obligation_id`, changes | supporting / contradicting artifacts, review findings |
| `obligation_closed` | `obligation_id`, `artifact_id`, `closure_mode`, `check_id`, verdict | VERIFY, only through `settlement.can_close_obligation` |
| `failure_signature_recorded` | `FailureSignature` (`FSIG-NNNN`, key, category, occurrences, ...) | a worker failed |
| `retry_refused` | `branch_id`, `signature_id`, `reason_code`, `why_refused` | SCHEDULE refused an unchanged repeat |
| `retry_allowed` | `branch_id`, `signature_id`, `why_different` | SCHEDULE allowed a retry because something changed |
| `coverage_assessed` | `coverage_ref` (`COV-NNNN`), insufficient, critical | MAP_LITERATURE, a librarian |
| `migration_recorded` | source paths, sha256s, `imported_at`, `importer_version` | `campaign import-research` |
| `diagnostic_recorded` | `Diagnostic` | the store or engine noticed something about the files themselves (the only event a terminal campaign still accepts) |
| `campaign_failed` | reason | an illegal phase transition or a missing handler (terminal) |
| `parallelism_capped` | requested, effective | `max_parallel_workers > 1` at start |
| `problem_normalized` | `NormalizedProblem` | NORMALIZE |

## Reducer and replay

`reducer.reduce(events)` folds a log into a `CampaignSnapshot`; `reducer.apply(snapshot,
event)` folds one event into a *new* snapshot (the input is never mutated). The
reducer is pure: no clock, no disk, no config -- ids are minted from counters that
live in the snapshot (`BRANCH-`, `WI-`, `OBL-`, `FSIG-`, `NODE-`) and are advanced
only when the reducer sees the event carrying the id, so replaying the log
reproduces exactly the same ids.

**What the snapshot holds**: phase, status, `resume_phase`, the reasons
(pause / stop / failure / completion), the `NormalizedProblem`, branches, work
items, obligations, failure signatures, the `BudgetLedger`, routing decision ids
and the last `RouteSummary`, artifact *references*, the coverage reference and
its insufficient categories, campaign proof-tree nodes, review and verification
references, diagnostics, counters, phase history, the current worker, and the
recent event ids.

**What it never holds**: claim statuses, the root's mathematical status, full
coverage assessments, full routing records. Those are read from their own
ledgers when a view needs them, so the snapshot cannot disagree with the
dossier.

The store keeps the two files consistent:

- `append` writes the event line (and `fsync`s it) **before** it folds the event
  into memory and rewrites `snapshot.json` atomically, so the snapshot is never
  ahead of the log; a crash between the two leaves a snapshot that `load` catches
  up by applying the tail. `campaign.persist_every_event: false` writes the
  snapshot at phase boundaries only; `verify` allows for that lag.
- `load` reads the snapshot and applies every event with `seq > snapshot.last_seq`;
  a missing, unreadable or *ahead-of-the-log* snapshot triggers a full replay and a
  `corrupt_snapshot` diagnostic (a snapshot naming another campaign is replaced by
  a full replay as well).
- `verify_replay` (`opentorus campaign verify`) recomputes
  `reduce(events with seq <= snapshot.last_seq)` and diffs it field by field
  against `snapshot.json`; a mismatch is reported per field and exits 1.
- A terminal campaign (`completed` / `stopped` / `failed`) accepts no further
  events except `diagnostic_recorded`.
- A phase move the table forbids raises `InvalidTransition` at append time
  (nothing written; the engine records `campaign_failed`); the same move in an old
  log is a diagnostic at replay time.

### Tolerance and diagnostics

Nothing is silently dropped. Each of these becomes a `Diagnostic{kind, message,
seq, line_no}` the caller sees (`campaign status` counts them, `campaign verify`
lists them):

| kind | when |
|---|---|
| `corrupt_line` | a torn trailing line (crash mid-append -- ignored, and the next append starts a fresh line); a corrupt line elsewhere; a line that is not a campaign event or whose payload fails its model |
| `corrupt_snapshot` | `snapshot.json` unreadable, invalid, or ahead of the log -- replaying the log |
| `seq_gap` | `seq` jumps (the events after it are kept) |
| `seq_duplicate` | a repeated `seq` (skipped) |
| `unknown_event_type` | a type this build does not know (preserved on disk, ignored by the reducer) |
| `invalid_payload` | a known type whose payload the reducer could not validate |
| `invalid_transition` | a phase move in an old log that the table forbids (skipped) |
| `migration` | reserved for a record upgraded on read (every migration is the identity today) |
| `parallelism_capped` | `max_parallel_workers > 1` |

`schema_version` stamps every event and snapshot; `store.MIGRATIONS[v]` upgrades a
raw event dict *to* version `v` and `migrate_events` runs a record through every
migration from its version + 1 to the current one (identity for v1). Unknown
fields are tolerated everywhere.

## Determinism

- **Clock.** Every timestamp comes from a `Clock` injected into the store and
  engine (`SystemClock` in production; `StepClock` / `FixedClock` in tests). The
  reducer copies event timestamps and never asks a clock; `SystemClock` is the
  only `datetime.now` in the package (a structural test greps for others).
- **Ids.** `CAMPAIGN-` and `RTD-` (routing decisions) come from workspace scans
  with `next_id`; everything inside a campaign is counter-derived; sessions are
  `CAMPAIGN-0001:BRANCH-0002:WI-0003`; no `uuid` anywhere in the layer.
- Two fresh mock workspaces therefore produce identical event sequences apart
  from wall-clock seconds and token counts, which the structural digest tests
  exclude (`tests/test_campaign_mock_run.py`); `snapshot == reduce(events)` is
  asserted after every engine test.

## Legacy research runs

`opentorus research` predates campaigns and keeps its own state
(`research/<slug>.json`, `journal/journal.jsonl`, the progress note, checkpoints).
Two bridges exist, both read-only towards those files:

- **Opt-in recording.** `opentorus research --campaign` (or
  `campaign.record_research: true`), *and* an attributed problem, mirrors the run
  into an exploration campaign under that problem while it runs: `imported_from:
  research:<slug>`, one numerical branch "Autonomous research: <question>", one
  work item per iteration with the `EXP-` / `EVIDENCE-` / `CLAIM-` ids as artifact
  references, walked through the real phase machine; completed when the run
  stops, left resumable at SCHEDULE if the process dies. A plain run writes
  exactly what it always wrote (`tests/test_research_facade.py`
  `test_plain_research_creates_no_campaign_dir`).
- **Import.** `opentorus campaign import-research QUESTION | --slug SLUG [--problem
  P] [--force]` converts a finished or interrupted legacy run the same way,
  replaying its journal entries. The first event after `campaign_created` is
  `migration_recorded` with the source paths, their sha256s, the import time and
  the importer version, and the campaign record carries `imported_from` and
  `migration_provenance`. The problem is resolved from `--problem`, else the run's
  target claim attribution, else the active problem; a run that fits no dossier
  is refused with the fix spelled out. The originals are read, never modified
  (a test compares their sha256 before and after); a second import of the same
  run is refused (exit 2) unless `--force`, which creates a further campaign,
  never a rewrite.

Either way the result is a normal campaign: `status`, `verify`, `tree` and the
dashboard work on it, and -- as everywhere -- its completion says nothing about
whether the problem is solved.
