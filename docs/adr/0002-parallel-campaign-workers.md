# ADR 0002: Parallel campaign workers

- Status: accepted
- Scope: `opentorus.campaign.concurrency`, `campaign.engine` (SCHEDULE / EXECUTE),
  `campaign.execution`, `campaign.scheduler`, `campaign.store`, `campaign.workers.base`
- Supersedes: the "v1 executes sequentially" clause of ADR 0001 (D4/D6 otherwise stand)

## Context

ADR 0001 accepted `campaign.max_parallel_workers` but capped it to 1 with a
`parallelism_capped` diagnostic. Campaign work is I/O bound on the model server
(vLLM / Ollama batch concurrent requests well), so a campaign with three active branches
spent most of its wall time with two of them idle. Making it concurrent had to keep
what the sequential engine guarantees:

- the event log is append-only with gap-free `seq`, a pure reducer, and a replay that
  `campaign verify` compares with the snapshot;
- a work item's artifacts are exactly what it produced (`artifact_created` attribution);
- the dossier ledgers mint ids by read-max-then-append, several without a file lock;
  session, usage and routing ledgers are appended by the agent loop;
- budgets are campaign-wide and must not be overspent;
- `max_parallel_workers == 1` (the default) stays byte-for-byte deterministic.

## Decision

| # | Decision |
|---|---|
| P1 | Threads, one per work item of a batch; a batch is up to `max_parallel_workers` items on **distinct** branches scheduled in one SCHEDULE pass and executed in one EXECUTE pass. The rest of the round (CRITIQUE, VERIFY, UPDATE_GRAPH, REALLOCATE) is unchanged. |
| P2 | One **work lock** (`ConcurrencyGate`) is held by a work item's thread for its whole run and released only while it waits for the provider (`GatedProvider` behind a `GatedPool`) or for an experiment subprocess (`exp_run` is wrapped). Every tool call, dossier write, id mint and ledger append therefore stays serialized; only the waiting overlaps. |
| P3 | Exact attribution from lock segments: whatever appeared in the artifact index while a thread held the lock is that work item's. It replaces the before/after window diff for batch items, and workers that look for "what is new since I started" drop ids a sibling created or touched (`WorkerRuntime.is_foreign`). The formalizer filters sibling proofs the same way, so no role is exclusive today; `EXCLUSIVE_ROLES` remains the hook for a future role that cannot. |
| P4 | Single writer: worker threads never append events; the engine thread records every result after the batch, in scheduled order. `CampaignStore.append` is additionally serialized by an `RLock`. |
| P5 | Budgets reserved before dispatch: each plan's `max_steps` is subtracted from what the next plan may take (`select_next(reserved_steps=...)`), so a batch cannot jointly exceed `max_steps`; tokens and cost left are split into equal per-item shares (`WorkBudget.tokens_remaining` / `cost_remaining_usd`); every loop's stop flag checks the recorded ledger **plus** the live spend of all in-flight items (`InFlight`). The campaign wall-clock ledger is charged the batch's elapsed time once (`BudgetConsumedPayload.campaign_wall_seconds`). |
| P6 | `max_parallel_workers == 1` never enters the new code; `parallelism_capped` is no longer emitted (the type stays readable for old logs). |

## Consequences

Easier:

- Wall time of a round is the slowest item, not the sum; model servers see concurrent
  requests.
- Nothing about the log, the reducer, replay or attribution changes for a reader.

Harder / accepted costs:

- A batch's event order follows the schedule, but dossier ids (CLAIM-, EXP-, ...) depend
  on which thread wrote first: a `P > 1` run is reproducible in structure, not in ids.
- Overspend of a shared token/cost budget is bounded, not zero: a model turn already in
  flight finishes (at most one turn per concurrent item). Steps are exact.
- Exact step reservation means a small `max_steps` relative to `branch_step_budget`
  yields smaller batches (each item reserves its branch's remaining steps).
- Tool execution is serialized across items: a worker whose time is spent in tools
  (not in the model or an experiment) gains nothing from parallelism.
