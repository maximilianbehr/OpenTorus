# ADR 0001: Campaign engine

- Status: accepted
- Scope: `opentorus.agent.control`, `opentorus.providers.{pool,capabilities}`,
  `opentorus.campaign`, `opentorus.research.theorems`, `opentorus.dashboard`,
  the `campaign` and `theorem` CLI groups, CI/release workflows

## Context

OpenTorus ran three mostly linear loops:

- `AgentLoop` (`agent/loop.py`), with every anti-loop guard inlined and the
  prove/literature recovery hint texts hard-coded next to them;
- `run_prove` (`agent/prove_loop.py`), which handed eight gate/hint/stall closures
  into `AgentLoop`;
- `run_research` (`agent/research_loop.py`), a fixed counterexample-search
  iteration with a per-question JSON state file.

Model routing (`governance.route_model`) was advisory metadata: the provider was
built once from `config.model` and never rebuilt, and the usage ledger recorded
`config.model.name` rather than the model that actually answered. Literature
completeness was a paper count. There was no persistent, resumable multi-branch
coordination, no typed proof tree with obligations, and theorem references
(`THM-*`) were unvalidated pointers used in one place.

The assignment: a persistent, portfolio-based campaign engine (typed append-only
event log plus deterministic reducer, branches with explicit root relations, a
deterministic scheduler, narrow worker roles, a semantic proof tree with
obligations, theorem-level literature, actual per-task provider routing with
auditable provenance, a `campaign`/`theorem` CLI, an optional read-only Textual
dashboard, build/wheel-install CI and a non-publishing tag-triggered release
workflow) -- without weakening any epistemic invariant (EVAL-001..008), breaking
`research`/`prove`, re-recording golden transcripts, or rewriting existing
dossiers.

Constraints that shaped every decision below (verified against the tree):

- Tests reach into `AgentLoop` private state (`_search_streak`,
  `_note_tool_failure`, `_deliverable_satisfied`, ...) and import module-level
  guard constants; `agent/verify.py`, `agent/executor.py` and
  `agent/prove_loop.py` do the same. Those names have to survive.
- Golden transcripts pin the mock path byte for byte; the REPL `/help` list is
  part of them.
- Every scalar config field must appear in `default_config.yaml`
  (`tests/test_config.py` template guard).
- Only a verification artifact may promote a claim; reports never upgrade
  evidence into proof; failed attempts are first-class.
- `session.jsonl` is rewritten by compaction, so it cannot be the reducer's
  input.

## Decision

| # | Decision |
|---|---|
| D1 | New packages: `opentorus.agent.control` (control plane), `opentorus.providers.{pool,capabilities}` (routing), `opentorus.campaign` (engine, persistence, workers, proof_tree), `opentorus.research.theorems` (THMREF), `opentorus.dashboard` (Textual, lazy), CLI `cli/campaign.py`, `cli/theorem.py`. |
| D2 | `AgentLoop` stays the public facade: every existing ctor param keeps name/order/default; new params keyword-only appended (`event_sink, routing, usage_tags, policies, should_stop`). Guards become pure policy classes returning `PolicyDecision`s with **exact current strings**; prove/lit hint texts move to `agent/control/legacy.py` (loop.py re-exports names). Golden transcripts unchanged. |
| D3 | Routing: `models.profiles` + `governance.routing.task_routes`; legacy `model:` = implicit `default` profile; legacy `task_models` honoured (incl. `"default"` fallback). `ProviderPool.acquire()` builds providers via a derived `Config` -> existing `get_provider`; **every** acquire appends a `RoutingDecisionRecord` to `.opentorus/usage/routing.jsonl`; `UsageRecord` gains routing/campaign fields; `ProviderResponse.model` + `BaseProvider.model_name` carry the actual model. Fallback never silent. |
| D4 | Campaign persistence: workspace-unique `CAMPAIGN-NNNN`; `events.jsonl` append-only typed events (`EVT-000001` from seq); pure reducer; atomic `snapshot.json` (orchestration state + artifact *references* only, never claim statuses); `campaign.yaml` record; corrupt tail/snapshot -> diagnostics + replay, never silent; `schema_version` + `migrate_events` hook; injectable clock. |
| D5 | Phase machine with explicit transition table; PAUSED stores `resume_phase`; STOPPED/COMPLETED terminal (resume idempotent, exit 0); per-mode completion policy; completion never touches claim status. |
| D6 | Portfolio: LLM strategist (JSON) with deterministic template fallback from `dossier/strategies.STRATEGY_TEMPLATES`; Jaccard dedup (`REPEATED_STRATEGY`), cap truncation (`PORTFOLIO_CAP`), explicit activation (`branch_activated`, top `max_active_branches`); each branch <-> dossier `Approach` (APPR-*). Scored, documented-heuristic scheduler with fairness/literature boost and id tie-breaks; failure signatures gate retries. Workers isolated by `WorkerContext` (artifact refs only, own session id). |
| D7 | Proof tree derived from campaign snapshot + dossier artifacts; obligations live in campaign events; closure only via `obligation_closed` citing an artifact validated by the same four checks as `claims._require_verification_artifact` (or COUNTEREXAMPLE_VERIFIED claim / referee pass on gap-free primary proof / accepted THMREF applicability). Root status = `status_gate` + `scope`. |
| D8 | THMREF is a **workspace-level** ledger (`.opentorus/theorems/`), optional `problem_id`/`root_relation`; existing `THM-*` untouched; extraction -> `candidate`; applicability computed deterministically (LLM may attach `proposed_analysis`); human `theorem review` is the only path to `accepted`; only accepted THMREF licenses `has_reference` in `report.honesty_context` (sole honesty-surface change, tested). |
| D9 | `research` keeps its documented behaviour; campaign recording is **opt-in** (`--campaign` / `campaign.record_research`); `campaign import-research` converts legacy state with provenance, originals untouched. `prove` keeps signature; acquires via pool; uses `NoProgressWindow`/`DeliverablePolicy`. |
| D10 | Primary claim in `prove-or-refute`: `campaign start` **creates the CONJECTURE claim from the statement and designates it primary by default** (the engine is the driver per `examples/CAMPAIGN_TEMPLATE.md` rule 3), status untouched, printed and recorded as `artifact_created`; `--no-primary-claim` refuses (exit 2 with `problem claim ... / problem verdict --set-primary` remediation). Exploration/survey need no primary claim. |
| D11 | Coverage levels: librarian may set at most `partial`; `adequate` requires an accepted THMREF or human override. Paper count never completes literature. |
| D12 | CI: extend `lint.yml` build job (sdist+wheel, twine check, clean-venv wheel **and** sdist installs + CLI smoke, import-without-textual, `[dashboard]` extra); new `release.yml` (v* tags; test -> build -> smoke -> SBOM (`anchore/sbom-action`) -> provenance attestation -> PyPI trusted publishing -> draft GitHub release), publish jobs gated by an unset repo variable; first-party actions by major tag (repo convention), third-party by commit SHA + version comment. `dev` extra gains `twine` + `textual` so dashboard pilot tests run in CI. Version not bumped. |
| D13 | Test double `ScriptedProvider(name, model_name, responses)` lives in `tests/support/providers.py` (not shipped). |

### Why an event log plus a reducer (D4)

The only append-only ledger the loops had was `actions.jsonl`, which carries no
session, task or campaign identity, and `session.jsonl` is rewritten in place by
compaction. A campaign that must be resumable, auditable and replayable needs a
log nothing else edits: typed events with a sequence number, a pure reducer that
turns them into a snapshot, and a snapshot that is only ever a cache of the
reduction (`campaign verify` recomputes it and reports any drift). Orchestration
state and artifact *references* live in the snapshot; claim statuses never do,
so the campaign layer cannot become a second source of truth for what is proved.

### Why the control plane comes first (D2)

The guards in `AgentLoop` are calibrated against recorded runs and their message
strings are the observable behaviour. Extracting them into pure classes with a
`PolicyDecision` result (action + reason code + the *same* message) is what lets
the campaign workers reuse them without duplicating thresholds, and what lets a
`WorkflowPolicySet` be composed per worker role. The facade keeps every private
name the tests and `prove_loop`/`executor`/`verify` reach for, so the extraction
is verified by characterization tests written before it
(`tests/test_control_plane_characterization.py`), not by re-recording anything.

### Why THMREF is workspace-level (D8)

A theorem is a fact about a paper, not about one problem: two dossiers citing
the same result must point at one validated locator with one review status.
Per-problem `THM-*` refs stay as they are; THMREF adds an optional attribution
(`problem_id`, `root_relation`) on top and is the only reference kind that can
license knowledge claims in the honesty context -- and only once a human has
accepted it.

## Consequences

Easier:

- One place (`agent/control/policies`) owns every threshold and every guard
  message; workers, `prove`, and `research` share them.
- Campaign runs are resumable after interruption or budget exhaustion, and
  auditable by replay; a corrupt tail is a diagnostic, not a crash and not a
  silent loss.
- Model choice is recorded per turn with the profile that was requested, the
  profile that answered, and why a fallback happened.
- Literature completeness becomes theorem-level and reviewable instead of a
  paper count.

Harder / accepted costs:

- `AgentLoop` carries a compatibility layer (delegating properties and
  methods) until callers migrate to the policy objects directly.
- Two ledgers (`usage/ledger.jsonl` and `usage/routing.jsonl`) instead of one;
  the routing decision id is the join key.
- `config set` cannot write mapping values (`models.profiles`, `task_routes`);
  those are hand-edited and documented as such.
- Campaign completion is an orchestration fact only; the root status is still
  derived from dossier artifacts. Users must not read "completed" as "solved",
  and the CLI says so.

## Non-goals

- No change to which artifacts may promote a claim; no new promotion path.
- No re-recorded golden transcripts, no new REPL slash commands.
- No version bump; the release workflow publishes nothing until a repository
  variable and a PyPI trusted publisher exist.
