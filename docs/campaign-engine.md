# The campaign engine

`opentorus campaign` runs a **campaign**: a persistent, resumable, portfolio-based
attack on one open problem. Where `opentorus prove` is a single budgeted session
and `opentorus research` a single counterexample loop, a campaign opens several
distinct lines of attack at once (branches), schedules bounded work items across
them with a documented heuristic, remembers what failed so it is not retried
unchanged, closes proof obligations only against accepted artifacts, and writes
every decision to an append-only event log you can replay.

The one sentence to keep in mind while reading the rest:

> **A campaign can finish without solving the problem.** Campaign status is
> orchestration state (phase, budget, branches, work items). The mathematical
> status of the problem is derived from the dossier's artifacts by
> `opentorus problem verdict` and the report status gate, and nothing a campaign
> does -- completing, closing an obligation, finishing a branch -- ever enters
> that derivation. A completed campaign whose problem is still `UNSOLVED` is the
> normal case.

Modules: `opentorus.campaign` (engine, lifecycle, phases, store, reducer,
portfolio, scheduler, failures, budget, workers, proof_tree, research_bridge,
importer), the CLI groups `opentorus.cli.campaign` / `campaign_tree` /
`campaign_dashboard`. Companion pages: [campaign-persistence.md](campaign-persistence.md)
(the files and events), [portfolio-scheduler.md](portfolio-scheduler.md) (how work
is chosen), [proof-tree.md](proof-tree.md) (obligations, root relations,
settlement), [theorem-references.md](theorem-references.md) (literature at theorem
level), [model-routing.md](model-routing.md) (which model answers for which task),
`docs/dashboard.md` (the optional read-only Textual dashboard, shipped with the
`dashboard` extra), and [adr/0001-campaign-engine.md](adr/0001-campaign-engine.md)
(why it is built this way).

## Modes

A campaign has one of three modes, chosen with `--mode` (default:
`campaign.default_mode`, shipped as `exploration`). The mode fixes the template
portfolio, the scheduler's bias, the critical literature categories and the
completion criterion.

| | prove-or-refute | exploration | survey |
|---|---|---|---|
| purpose | settle a quantified conjecture either way | learn structure, gather evidence | map the literature |
| template portfolio (kind / root relation), in recipe order | proof / equivalent; counterexample / counterexample-route; literature / supporting; formalization / equivalent; special-case / special-case (child of the proof branch); obstruction / supporting; symbolic / supporting | numerical / supporting; counterexample / counterexample-route; literature / supporting; special-case / special-case | one literature branch per critical coverage category, then one synthesis branch |
| mandatory branches | at least one proof branch **and** one counterexample branch stay active | none | none |
| scheduler bias | root impact by relation (equivalent 1.0, counterexample-route 0.9, ...); the resolve-chance table favours proof and counterexample branches (0.6); literature boosted while critical coverage is insufficient | same factors; the resolve-chance table favours numerical and counterexample work (0.6), then literature (0.5) | literature (0.8) and synthesis (0.7) lead the resolve-chance table; literature branches always carry the literature boost |
| critical coverage categories | original source, definitions, strongest positive results, negative results, counterexamples, equivalent formulations, standard tools | original source, definitions, special cases, standard tools | all eleven |
| completion (first that holds) | root settled per dossier artifacts (`GENERAL_CONJECTURE_PROVED` / `_REFUTED`); no active or proposed branch remains; a budget axis exhausted | a budget axis exhausted; no runnable branch remains | no insufficient critical category remains (after a coverage assessment); a budget axis exhausted; no runnable branch remains |
| primary claim | required; created and designated by `campaign start` (see below) | not needed | not needed |
| minimum `--branches` | 2 | 1 | 1 |

"Root settled" is read from the dossier (`scope.classify_outcome` and
`status_gate.derive_status`), never inferred from the campaign; the criterion is
how a prove-or-refute campaign notices that *someone* -- a verifier, a human --
settled the problem, not a way to settle it.

## The workflow

```
   campaign start PROBLEM-0001
          |
          v
   CREATED --> INGEST --> NORMALIZE --> MAP_LITERATURE --> GENERATE_PORTFOLIO
                                                                  |
              +---------------------------------------------------+
              |
              v
   +------> SCHEDULE ------> EXECUTE ------> CRITIQUE ------> VERIFY
   |            |                                                |
   |            | (nothing runnable)                             v
   |            |                              REALLOCATE <-- UPDATE_GRAPH
   |            |                                   |
   |            |          (not complete)           |  (mode criterion met)
   +------------|-----------------------------------+
                |                                   |
                +-----------------> SYNTHESIZE <----+
                                        |
                                        v
                                    COMPLETED

   any working phase --> PAUSED (resumes at the phase it left) | STOPPED | FAILED
```

Every arrow is a `phase_completed` + `phase_entered` pair in the event log; the
transition table lives in `campaign.phases.PHASE_TRANSITIONS` and is enforced at
append time (an illegal move raises before anything is written and the engine
records `campaign_failed`) and at replay time (an illegal move in an old log
becomes a diagnostic, never a crash). One round of the loop is SCHEDULE ->
EXECUTE -> CRITIQUE -> VERIFY -> UPDATE_GRAPH -> REALLOCATE.

| phase | what happens | events |
|---|---|---|
| INGEST | reads `statement.md`, pins its sha256 as the first artifact reference, notes when the statement changed since `campaign.yaml` was written | `artifact_created` (kind `problem_statement`) |
| NORMALIZE | builds the `NormalizedProblem` every worker sees -- statement, target scope (`scope.classify_target`), recorded assumptions and definitions, the primary claim id -- from dossier facts only | `problem_normalized` |
| MAP_LITERATURE | the librarian derives a category coverage map (`theorems.coverage.assess_coverage`, at most `partial` from dossier facts) | `coverage_assessed` (`COV-NNNN`, insufficient and critical categories) |
| GENERATE_PORTFOLIO | strategist proposals (LLM JSON with a real provider, the mode's template otherwise), de-duplication, cap, activation; one dossier `Approach` (`APPR-*`) per accepted branch whose strategy is one of the eight dossier templates | `branch_proposed`, `branch_rejected` (`REPEATED_STRATEGY` / `PORTFOLIO_CAP` / `ROOT_RELATION_REQUIRED`), `branch_activated`, `artifact_created`, `budget_consumed` (strategist turns) |
| SCHEDULE | scores every runnable branch and picks one work item; refuses to re-run a recorded failure unchanged (`retry_refused` and `branch_suspended`); activates a queued branch when nothing else is runnable; hands over to SYNTHESIZE when nothing at all is | `work_item_created`, `work_item_scheduled` (with the full `ScoreBreakdown`), `retry_refused` / `retry_allowed`, `branch_suspended` |
| EXECUTE | runs the scheduled work item through its worker inside its own context and budget; the campaign-wide governance caps are checked first (usage ledger, `campaign_id`-scoped) | `worker_started`, `worker_completed` / `worker_failed`, `artifact_created`, `obligation_created`, `failure_signature_recorded`, `budget_consumed`, `verification_recorded` |
| CRITIQUE | the critic reviews the round's new claims and proof attempts (`agent.review.review_target` + the hostile referee); downgrades are recommended, never applied | `review_requested`, `review_recorded` |
| VERIFY | the verifier-coordinator asks `proof_tree.settlement.can_close_obligation` for every open obligation and proposes closures **only** for accepted artifacts | `obligation_closed` |
| UPDATE_GRAPH | mirrors new artifact references and obligations as campaign proof-tree nodes | `proof_node_created` / `proof_node_updated` |
| REALLOCATE | budget check (a newly spent axis pauses the campaign), suspension of branches with repeated identical failures, exhaustion of branches out of step budget, reactivation only when a recorded condition is met, activation of queued branches, then the mode's completion criterion | `budget_exhausted`, `campaign_paused`, `branch_suspended` / `branch_exhausted` / `branch_reactivated` / `branch_activated` |
| SYNTHESIZE | the synthesizer rewrites `progress.md` and rebuilds the dossier report; the campaign completes with the mode's criterion **and the problem status per dossier in the same sentence** | `campaign_completed` (`reason`, `mode_criterion`) |

The engine has exactly one `_phase_<name>` method per working phase
(`tests/test_engine_structure.py` pins that) and imports no claim-status
mutator: everything it learns about the mathematics it learns by reading
dossier artifacts.

## Branches

A branch is one line of attack: a `BranchRecord` with a `kind`, an `objective`,
a `strategy_summary`, its `root_relation`, an `assumption_context`, an optional
`parent_branch_id`, `dependencies`, a `priority`, a `status`, its work items,
artifact references, failure signatures, and -- when the strategist proposed it
from a template -- the dossier `Approach` id (`APPR-*`) and `strategy_key`
(`proof_sketch`, `counterexample_search`, ...).

Kinds: `proof`, `counterexample`, `literature`, `special-case`, `symbolic`,
`numerical`, `formalization`, `obstruction`, `synthesis`.

Statuses and how they move:

```
   proposed --> active --> completed
      |          |  ^
      |          |  +--- reactivated (a recorded condition was met)
      |          v
      |       suspended (repeated identical failure; branch out of budget
      |          |       with a condition to wait for)
      |          v
      |       exhausted (branch step budget spent)
      v
   rejected (REPEATED_STRATEGY duplicate, PORTFOLIO_CAP overflow, ROOT_RELATION_REQUIRED
             when a proposal names no relation and the config requires one; kept, not deleted)
```

### Root relations

Every branch (and every obligation) states how its target relates to the root
problem. `campaign.require_root_relation` (default on) makes the strategist say
so; a template branch always carries one. The relation decides what settling the
branch could ever mean for the root -- the full rules are in
[proof-tree.md](proof-tree.md); this is the summary:

| relation | settling it settles the root? | condition |
|---|---|---|
| `equivalent` | yes | the equivalence itself is justified (verified both ways, or an accepted reference) |
| `sufficient` | proving direction only | the reduction is verified and every obligation it opens is closed |
| `necessary` | refuting direction only | needs the converse to prove anything |
| `counterexample-route` | yes, negatively | an accepted witness that satisfies every root assumption and violates the conclusion |
| `special-case` | **never** | a proof of a subclass leaves the general statement open |
| `relaxation` | **never** | a weaker statement neither proves nor refutes the stronger one |
| `supporting` | never | informs the attack |
| `unrelated`, `unknown` | never | classify first |

The proof-tree validator turns a special-case or relaxation node with a
`closes` / `verifies` / `refutes` edge into the root into an error
(`special_case_root_closing`), and the plain tree view marks every non-settling
relation with a subset glyph so a closed special-case obligation can never be
read as the root being settled. A special-case branch's prover writes
*exploration* sketches with a bridge to the primary answer, never the dossier's
primary answer itself.

## Worker roles

A work item is executed by exactly one worker role. Roles are narrow on purpose:
each has a task class for routing, a fixed tool allow-list, and one kind of
output.

| role | task class | what it does | tools |
|---|---|---|---|
| strategist | `campaign_strategy` | proposes the portfolio (JSON) or falls back to the template | no tool loop: one routed model turn |
| prover | `proof_development` | bounded `prove` loop; writes a `PROOF-*` sketch; every explicit gap becomes an obligation proposal | dossier tools + `proof_write`, `proof_submit`, `exp_new`, `exp_run`, known-result / related-paper adds |
| falsifier | `counterexample_search` | designs and runs counterexample searches (`EXP-*`); a witness is strong contradicting evidence, status untouched | dossier tools + `exp_new`, `exp_run` |
| numerical-experimenter | `numerical_experiment_design` | numerical / validated-numerics experiments; bounds evidence | dossier tools + `exp_new`, `exp_run` |
| symbolic-experimenter | `symbolic_experiment_design` | sympy certificates via the verifier ledger | dossier tools + `exp_new`, `exp_run`, `proof_submit` |
| formalizer | `formalization` | Lean / Coq / SMT submissions; `tool_unavailable` when no formal backend is enabled | dossier tools + `proof_submit`, `proof_write` |
| librarian | `literature_synthesis` | coverage assessment (never above `partial`) | dossier tools + `paper_add`, known-result / related-paper adds |
| critic | `adversarial_critique` | reviews the round's new claims and proof attempts; runs the referee | no tool loop (deterministic) |
| verifier-coordinator | `verification_support` | closure proposals for accepted artifacts only | no tool loop (deterministic) |
| synthesizer | `final_synthesis` | `progress.md` and the dossier report | no tool loop (deterministic) |

("dossier tools" = `read_file`, `write_file`, `list_files`, `glob_files`,
`memory_add`, `paper_list`, `paper_read`, `paper_fetch`, `lit_search`,
`claim_new`, `evidence_add`, `kb_query`; the table is
`workers.base.ROLE_ALLOWED_TOOLS`.)

**Contract.** `Worker.run(ctx: WorkerContext, rt: WorkerRuntime) -> WorkerResult`.
A worker does one bounded piece of work and reports; ordinary failures are
returned as `status="failed"` with an `error_category`, never raised. The engine
turns the result into events; a worker never writes campaign events itself and
never sets a claim status.

**Isolation.** `WorkerContext` is frozen and carries ids and references only:
the campaign / branch / work item ids, the role and task class, the
`NormalizedProblem`, the branch objective and strategy summary, its root relation
and assumption context, `shared_artifacts` (references restricted to verified /
accepted artifacts), the theorem references, the failure signatures and open
obligations it should know about, its `WorkBudget`, `allowed_tools`, an
`output_schema`, and its **own session id** (`CAMPAIGN-0001:BRANCH-0002:WI-0003`).
There is no field for a transcript, and no worker ever sees another branch's
session (`tests/test_campaign_workers.py` asserts both). Model-driven roles run an
`AgentLoop` on a registry restricted to the role's tools, with a tool gate that
refuses anything else, the work item's step cap, the engine's event sink and stop
flag, and a provider **leased from the pool** for the role's task class, so the
routing decision id and the campaign / branch / work item / role tags land on
every usage-ledger row.

**Result.** `WorkerResult{status: completed | failed | blocked | branch_done,
artifacts_created, proposed_nodes, obligations, closure_proposals,
failure_signature, usage, routing_decision_id, notes, reviews, verifications,
target_claim_id}`. `branch_done` completes the branch (a librarian that has
assessed coverage; a synthesis branch that has been written).

Offline, under the mock provider, every role has a deterministic and honest
behaviour (the falsifier fails an unmodified template search with
`no_witness_found` and records no evidence; the formalizer reports
`tool_unavailable`; the prover writes a scaffold sketch with a gap that becomes an
obligation), so a mock campaign exercises the whole machine and closes nothing.
The per-role table is in [portfolio-scheduler.md](portfolio-scheduler.md).

## Failure signatures and retry rules

Every worker failure is summarised as a `FailureSignature` (`FSIG-NNNN`,
`failure_signature_recorded`). Its `key` is a sha256 over the *normalised* facts
that decide whether a retry is the same attempt -- `strategy_class`,
`target_obligation`, sorted `assumption_context`, `tool_or_solver`,
`error_category`, `counterargument` -- and deliberately not over artifact ids or
occurrence counts. A repeat of a known key reuses the signature and bumps
`occurrences`.

Error categories: `tool_unavailable`, `verifier_rejected`, `verifier_inconclusive`,
`no_witness_found`, `citation_invalid`, `permission_blocked`, `budget`, `timeout`,
`model_no_progress`, `other`.

Retry rules:

- Before scheduling a work item on a branch whose latest work item failed, the
  engine computes what changed since that signature (`RetryChanges`: assumptions,
  target obligation, new accepted theorem references, new evidence, solver,
  parameter regime, verification backend, human override -- every flag derived
  from the snapshot and dossier facts, never guessed).
- Nothing changed: `retry_refused` (`REPEATED_IDENTICAL_FAILURE`) and the branch is
  `suspended` with explicit `ReactivationCondition`s that record what was observed
  at suspension. Conditions follow the category: `verification_backend_changed`
  for backend categories, `new_evidence_count` for `no_witness_found` /
  `model_no_progress`, `theorem_ref_accepted` for `citation_invalid`,
  `human_override` otherwise.
- Something changed: `retry_allowed`, and `why_different` is appended to the
  signature's `retry_notes`.
- REALLOCATE also suspends a branch with two or more trailing identical failures,
  exhausts a branch that spent its `branch_step_budget` (`BRANCH_EXHAUSTED`), and
  reactivates a suspended branch **only** when a recorded condition is met by the
  current facts (`branch_reactivated`). Suspended branches do not keep a campaign
  alive: when nothing else is runnable the campaign completes and names them as
  waiting for their conditions.

## Budgets

Limits follow the config convention **`0 = not configured / unlimited`** on every
axis. `campaign start` refuses a campaign with no positive limit on any axis
(exit 2): an unbounded campaign is not a campaign.

| scope | limit | where it is charged |
|---|---|---|
| campaign | `max_steps` (model turns across all workers), `token_budget`, `cost_budget` (USD), `max_wall_seconds`; plus the workspace governance caps (`governance.budgets.token_budget` / `cost_budget_usd`) frozen into the campaign | `BudgetLedger` in the snapshot; `budget_consumed` per work item |
| branch | `branch_step_budget` model turns | `per_branch`; a branch that spent it is `exhausted` |
| work item | `WorkBudget.max_steps = min(branch steps left, campaign steps left)`; a work item that makes no model call is charged one step so an offline campaign terminates | `per_work_item` |
| model invocation | counted (`model_invocations`) | `budget_consumed` with scope `model_invocation` |
| tool execution | counted (`tool_executions`) | scope `tool_execution` |
| experiment | counted (`experiments_run`) | scope `experiment` |

The engine also asks `governance.assert_within_budget(..., campaign_id=)` before
every work item, so the workspace caps bound the campaign across every session
it ran, not just the current process.

Exhaustion is announced once per axis (`budget_exhausted`, the axis lands in the
ledger's `exhausted` list) and the campaign is **paused** with reason
`BUDGET_EXHAUSTED`. That is a valid, resumable state: raise the limit in
`config.yaml`, or simply `campaign resume` -- a resume that finds the same axes
still spent lets the mode's completion criterion end the campaign (`budget`)
instead of pausing forever. `max_parallel_workers > 1` is accepted but capped to
1 with a `parallelism_capped` event: v1 executes work items sequentially.

## Configuration

Every key of the `campaign:` block in `config.yaml`, with its shipped default.
CLI flags override per run; the effective values are frozen into `campaign.yaml`
so a resume months later runs under the same rules.

| key | default | meaning |
|---|---|---|
| `campaign.default_mode` | `exploration` | mode when `--mode` is omitted (`prove-or-refute`, `exploration`, `survey`) |
| `campaign.initial_branches` | `4` | proposals kept after de-duplication (`--branches` overrides) |
| `campaign.max_active_branches` | `3` | branches scheduled concurrently; the rest wait as `proposed` |
| `campaign.max_parallel_workers` | `1` | v1 executes sequentially; a larger value is capped to 1 with a diagnostic |
| `campaign.max_steps` | `50` | model turns across all workers; 0 = unlimited (`--max-steps`) |
| `campaign.max_wall_seconds` | `0` | wall-clock budget for the whole campaign; 0 = unlimited (`--max-wall-seconds`) |
| `campaign.token_budget` | `0` | tokens across all workers; 0 = unlimited (`--token-budget`) |
| `campaign.cost_budget` | `0.0` | USD across all workers; 0 = unlimited (`--cost-budget`) |
| `campaign.branch_step_budget` | `10` | model turns per branch before it is exhausted |
| `campaign.require_literature_mapping` | `true` | keep a literature branch while critical coverage is insufficient |
| `campaign.require_root_relation` | `true` | every branch must declare its relation to the root |
| `campaign.persist_every_event` | `true` | rewrite `snapshot.json` after every event (`false` = at phase boundaries only) |
| `campaign.record_research` | `false` | opt-in: `opentorus research` also records an exploration campaign |
| `campaign.scheduler_weights.novelty` | `1.0` | multiplier for the scheduler's novelty factor |
| `campaign.scheduler_weights.root_impact` | `1.0` | ... root impact / information gain / resolve chance |
| `campaign.scheduler_weights.verifier_readiness` | `1.0` | ... verifier readiness |
| `campaign.scheduler_weights.dependency` | `1.0` | ... dependency criticality |
| `campaign.scheduler_weights.cost` | `1.0` | ... cost penalty |
| `campaign.scheduler_weights.redundancy` | `1.0` | ... redundancy penalty |
| `campaign.scheduler_weights.failure` | `1.0` | ... failure-risk penalty |

Scalars round-trip through `opentorus config set campaign.<key> <value>` (an old
`config.yaml` without a `campaign:` block gains one on the first write). Which
model answers for which worker is configured separately, in `models.profiles`
and `governance.routing.task_routes` -- see [model-routing.md](model-routing.md).

## CLI walkthrough

All commands accept `--help`; the group help itself states the two-status rule.
`CAMPAIGN-NNNN` ids are workspace-unique, so no command needs the problem id.

```
opentorus problem new "For every n >= 1, P(n) holds."
opentorus campaign start PROBLEM-0001 --mode prove-or-refute --branches 4 --max-steps 40
```

`start` prints the campaign id on its own line first (`CAMPAIGN-0001`) so scripts
can capture it, then the status summary. In prove-or-refute mode it first creates
the CONJECTURE claim from the statement and designates it primary (see below).
Under the offline mock provider the run above completes in a few seconds with a
literature branch completed, a proof branch exhausted with two open obligations,
the counterexample and formalization branches suspended with honest failure
signatures, three overflow proposals rejected, and -- as it must -- the problem
status still `HEURISTIC_ONLY` / `NUMERICAL_EVIDENCE`.

Options: `--mode`, `--branches`, `--max-steps`, `--token-budget`,
`--max-wall-seconds`, `--cost-budget`, `--no-primary-claim`, `--no-run` (create and
record the campaign, run nothing; it reads `created` until the first `resume`).

```
opentorus campaign status CAMPAIGN-0001
```

```
Campaign CAMPAIGN-0001 on PROBLEM-0001  mode=prove-or-refute
  campaign status: completed  phase: completed
  completed: no active or proposed branches remain; problem status per dossier: NUMERICAL_EVIDENCE
  budget: steps 13 / 40, tokens 43330 / unlimited, cost 0 USD / unlimited, wall 0.556s / unlimited
  branches: completed=1, exhausted=1, rejected=3, suspended=2  rounds: 6  artifacts: 9
  obligations: open=2 closed=0
  coverage: COV-0002  insufficient: original_problem_source, definitions_notation, ...
  last route: RTD-0004 proof_development -> default
  problem status (derived from dossier artifacts, not from this campaign): NUMERICAL_EVIDENCE; report status HEURISTIC_ONLY
  note: campaign status != problem status -- a completed campaign does not mean the problem is solved; see `opentorus problem verdict`.
  latest events:
    EVT-000155 phase_entered phase synthesize (from schedule)
    EVT-000156 campaign_completed no active or proposed branches remain; ... [no_branches]
```

(The real note line uses an em dash and the coverage line lists every category;
both are shortened here to keep this file ASCII.)

`opentorus campaign status CAMPAIGN-0001 --json` emits the same
`CampaignStatusSummary` as JSON (`campaign_id`, `problem_id`, `mode`, `phase`,
`status`, `resume_phase`, the reasons, `branch_counts`, `obligations_open` /
`_closed`, the `budget` ledger, `latest_events`, `root_math_status`,
`current_worker`, `last_route`, `diagnostics`, `coverage_ref`,
`insufficient_categories`, `rounds`, `steps_executed`, `last_seq`,
`artifact_count`, timestamps).

```
opentorus campaign pause CAMPAIGN-0001 --reason "reviewing the sketch"
opentorus campaign resume CAMPAIGN-0001
opentorus campaign stop CAMPAIGN-0001 --reason "superseded by CAMPAIGN-0002"
```

`pause` records the reason and the phase to resume at; `resume` continues a
paused campaign there (and prints `... is already completed; nothing to resume.`
with exit 0 on a terminal one -- resume is idempotent); `stop` is terminal (the
log and every artifact stay; `--reason` is required). Ctrl-C during `start` /
`resume` pauses the campaign with reason `interrupted` and exits 130.

```
opentorus campaign list [--problem PROBLEM-0001] [--json]
opentorus campaign verify CAMPAIGN-0001 [--json]
opentorus campaign tree CAMPAIGN-0001 [--plain|--json|--dot] [--kind obligation] [--status open] [--depth 2] [--out tree.txt]
opentorus campaign dashboard CAMPAIGN-0001 [--live] [--plain|--json|--dot]
opentorus campaign import-research "the question" | --slug SLUG [--problem PROBLEM-0001] [--force]
```

`verify` replays `events.jsonl` and compares the reduction with `snapshot.json`
(`replay matches snapshot (156 events replayed; ...)`), listing diagnostics such as
a torn trailing line; `tree` renders the semantic proof tree
([proof-tree.md](proof-tree.md)); `dashboard` opens the read-only Textual view
(needs `pip install 'opentorus[dashboard]'`; the export flags work without it);
`import-research` converts a legacy `research` run into an exploration campaign
with provenance ([campaign-persistence.md](campaign-persistence.md)).

Exit codes:

| code | meaning |
|---|---|
| 0 | ok (including `resume` on a completed / stopped campaign) |
| 1 | error: unknown campaign or problem, unreadable workspace; `verify` replay mismatch; `tree` with more than one output flag |
| 2 | refused configuration: unknown `--mode`; `--branches < 2` in prove-or-refute (or `< 1` elsewhere); a negative budget; no positive budget on any axis after merging config and flags; prove-or-refute with `--no-primary-claim` and no designated primary claim; `import-research` of a run already imported (without `--force`) |
| 130 | interrupted (`start` / `resume`); the campaign is paused with reason `interrupted` |

## The rules that do not bend

- **A campaign can finish without solving the problem.** `campaign_completed`
  carries the mode's criterion (`root_settled`, `no_branches`, `budget`,
  `coverage`, `no_work`) and the problem status per dossier in the same sentence;
  `status`, `list`, `stop`, `progress.md` and the tree all print the two-status
  note. Completion never touches a claim status (`tests/test_campaign_engine.py`,
  `tests/test_settlement.py`).
- **Special cases and relaxations cannot close the root.** Their branches and
  obligations are marked, and an edge from them into the root is a validation
  error.
- **Campaign status is not problem status.** Read the former with
  `campaign status`, the latter with `opentorus problem verdict PROBLEM-0001`; the
  snapshot holds no claim status and no root status, so the two cannot drift.
- **Obligations close only against accepted artifacts.** The verifier-coordinator
  proposes, `settlement.can_close_obligation` decides, the engine records
  `obligation_closed`; deleting a `[GAP-n]` marker closes nothing.
- **The primary claim in prove-or-refute.** `campaign start` creates the
  CONJECTURE claim from the statement and designates it primary by default -- the
  engine is the campaign driver, so designating the target is its job. The claim's
  status is whatever a new CONJECTURE gets (`unverified`); nothing changes it, no
  `status_changes` entry is written, and the creation is printed and recorded as
  `artifact_created`. `--no-primary-claim` refuses (exit 2) and prints the manual
  remediation: `opentorus problem claim PROBLEM-0001 --type CONJECTURE --statement
  "..." && opentorus problem verdict PROBLEM-0001 --set-primary CLAIM-XXXX`.
  Exploration and survey campaigns need no primary claim.
- **Research recording is opt-in.** `opentorus research` writes exactly what it
  always wrote; only `--campaign` (or `campaign.record_research: true`) *and* an
  attributed problem add an exploration campaign mirroring the run.
- **Failed attempts are first-class.** Rejected proposals, refused retries and
  every failure signature stay in the log; nothing is silently retried.
