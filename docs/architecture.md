# Architecture

OpenTorus is a local-first, terminal-native agent. This document describes how
the pieces fit together and the boundaries that keep it inspectable.

## High-level shape

```
            +------------------------------------------------------------+
   user --> |  CLI / REPL / TUI  (opentorus.cli, .repl, .tui)             |
            |  problem ... | prove | research | campaign ... | theorem ...|
            +------------------------------+-----------------------------+
                                           | commands & interactive turns
            +------------------------------v-----------------------------+
            |  Campaign engine  (opentorus.campaign)                      |
            |  phases -> portfolio -> scheduler -> workers -> proof tree  |
            |  event log + reducer + snapshot (resumable, replayable)     |
            +------------------------------+-----------------------------+
                                           | work items (own session, budget, tools)
            +------------------------------v-----------------------------+
            |  Agent loops  (opentorus.agent)                             |
            |  AgentLoop facade / prove_loop / research_loop              |
            |  control plane: policies, TurnRunner, event sinks           |
            +------+-------------------+-------------------+-------------+
                   |                   |                   |
       +-----------v------+  +---------v---------+  +------v----------------+
       | Providers        |  | Tools +           |  | Research stack        |
       | pool + routing   |  | Permissions       |  | claims, evidence,     |
       | ledger; profiles |  | + Execution       |  | papers, theorems,     |
       | mock/openai/     |  | backends          |  | verifiers, KB, ...    |
       | anthropic/ollama |  |                   |  |                       |
       | /mistral         |  |                   |  |                       |
       +------------------+  +---------+---------+  +----------+------------+
                                       |                       |
                             +---------v-----------------------v---------+
                             |  .opentorus/  (project memory)            |
                             |  JSONL + YAML artifacts, dossiers,        |
                             |  campaigns, usage + routing ledgers       |
                             +-------------------------------------------+

   optional, read-only:  opentorus.dashboard (Textual; `pip install 'opentorus[dashboard]'`)
```

## Layers and boundaries

- **CLI / REPL / TUI** (`opentorus.cli`, `opentorus.repl`, `opentorus.tui`):
  the only user-facing surface. The interactive dispatch core is kept testable
  and separate from rendering.
- **Campaign engine** (`opentorus.campaign`): the persistent, portfolio-based
  attack on one problem. `engine.CampaignEngine` walks an explicit phase machine
  (`phases`), the strategist proposes a portfolio of distinct branches
  (`portfolio`), a documented heuristic scheduler picks bounded work items
  (`scheduler`), failed attempts become signatures that gate retries
  (`failures`), narrow worker roles execute in isolated contexts (`workers/`),
  and obligations close only against accepted artifacts (`proof_tree/settlement`).
  Every decision is an event in an append-only log; a pure reducer derives the
  snapshot (`events`, `reducer`, `store`). Campaign completion is orchestration
  only -- the problem's status stays derived from dossier artifacts. See
  [campaign-engine.md](campaign-engine.md), [campaign-persistence.md](campaign-persistence.md),
  [portfolio-scheduler.md](portfolio-scheduler.md), [proof-tree.md](proof-tree.md).
- **Agent loops** (`opentorus.agent`): the synchronous task loop
  (`agent.loop.AgentLoop`), the proof session (`agent.prove_loop`) and the
  long-horizon, budgeted `agent.research_loop` (whose iteration body lives in
  `agent.research_iteration`). Loops plan, request tool calls, record each step
  with its permission decision, and feed results back to the provider.
- **Control plane** (`opentorus.agent.control`): the pieces the loops are
  assembled from, so a campaign worker can compose the same guards without
  inheriting the loop's control flow. `policies/` holds the anti-loop guards,
  budgets, no-progress windows, deliverable and permission rules as pure objects
  returning typed `PolicyDecision`s (action + stable `ReasonCode` + the same
  message the loop always printed); `TurnRunner` performs one provider turn or
  tool execution; `events` defines the run event sinks; `phase_machine` is the
  generic transition checker the campaign phases use. `AgentLoop` remains the
  facade every caller uses, and the extraction is pinned by characterization
  tests, not by re-recorded transcripts.
- **Providers** (`opentorus.providers`): a `BaseProvider` interface with
  `MockProvider` (offline, deterministic — the default) plus optional OpenAI,
  Anthropic, and Ollama backends. The provider never leaks into core logic; tool
  calling is normalized across providers. `providers.pool.ProviderPool` leases the
  provider for a *task class* from named profiles (`models.profiles`) and routes
  (`governance.routing.task_routes`), records every decision in
  `.opentorus/usage/routing.jsonl`, and never falls back silently;
  `providers.capabilities` says what a profile can do (static table, declared
  list, doctor's probe cache). See [model-routing.md](model-routing.md).
- **Tools + permissions** (`opentorus.tools`, `opentorus.permissions`): an
  abstract `Tool` interface with `ToolCall`/`ToolResult` schemas and a registry.
  Every effecting action is gated by the permission policy (mode + operating
  style + review mode) with non-bypassable hard guarantees.
- **Execution backends** (`opentorus.execution`): a neutral `ExecutionBackend`
  protocol with local, Docker, Podman, Apptainer, SSH (remote), and Slurm (HPC)
  implementations, plus digest pinning, sandboxed mounts, and a result cache.
- **Research stack** (`opentorus.research`): claims, evidence, the artifact
  graph, experiments and manifests, literature sources, papers and the hybrid
  index, datasets, repos, verifiers (Lean/Coq/SMT), figures, authoring, packs,
  the cross-workspace knowledge base, and `research.theorems` -- theorem-level
  literature: located `THMREF-*` references, typed relations, deterministic
  applicability checks and category coverage, where only a human review reaches
  `accepted` (see [theorem-references.md](theorem-references.md)).
- **Dashboard** (`opentorus.dashboard`, optional): a read-only Textual view of a
  campaign's proof tree, imported lazily behind the `dashboard` extra so the core
  CLI never needs it (`opentorus campaign dashboard`; `docs/dashboard.md`).
- **Governance** (`opentorus.governance`, `opentorus.research.egress`,
  `opentorus.usage`): pre-egress DLP, per-provider/investigation budgets (also
  campaign-scoped), the compatibility wrapper `route_model` over the pool, and
  the usage ledger -- every row now carries the actual provider and model plus
  routing and campaign provenance.

## Data flow through a campaign

1. `opentorus campaign start PROBLEM-XXXX` validates the request (mode, branches,
   budgets; in prove-or-refute the CONJECTURE primary claim is created and
   designated), allocates a workspace-unique `CAMPAIGN-NNNN`, and writes
   `campaign.yaml` + the first event.
2. The engine walks INGEST -> NORMALIZE -> MAP_LITERATURE -> GENERATE_PORTFOLIO,
   then rounds of SCHEDULE -> EXECUTE -> CRITIQUE -> VERIFY -> UPDATE_GRAPH ->
   REALLOCATE until the mode's completion criterion holds, a budget axis is
   exhausted (pause, resumable) or the user pauses/stops.
3. Each work item runs one worker role in a frozen `WorkerContext` (artifact
   references, own session id, budget, allowed tools -- no transcripts) with a
   provider leased from the pool for the role's task class; the worker's
   `AgentLoop` is the loop below, bounded by the work item.
4. Results become events (artifacts, obligations, failure signatures, budget);
   claim statuses are never written by this layer. `campaign status`, `verify`,
   `tree` and the dashboard read the log and the dossier; `problem verdict`
   derives the mathematical status from the dossier alone.

## Data flow through a loop

1. The user issues a command or interactive turn.
2. The loop assembles **context** (transparent, retrieval-driven, honoring the
   privacy filter) and asks the provider for the next step. The request is ordered
   *stable first*: system prompt, tool-routing guide, run goal, then history, and only
   then the volatile block (workspace inventory, retrieval hits, recovery hint), which
   is inserted just ahead of the final turn. A local server can reuse its KV cache only
   for a prefix it has already seen, and the inventory changes almost every step — with
   it near the front, the whole history behind it was re-evaluated on every call
   (measured: 96% of processed tokens were re-sent prompt). Set
   `context.stable_prefix: false` for the previous ordering.
   A run is bounded by `agent.max_steps`, by the cost/token budgets, and — because
   every other guard assumes turns come back — optionally by `agent.max_wall_seconds`,
   checked between steps.
3. If the provider requests a tool, the **permission policy** decides
   allow / ask / block. Allowed tools execute (possibly inside an execution
   backend); the call, result, and decision are appended to the action log.
4. Effects produce or update **artifacts** under `.opentorus/`.
5. The result is fed back to the provider for the next step or a final answer.

## Design rules

- **Local-first**: all state is files under `.opentorus/`; no hidden cloud state.
- **Deterministic where possible**: ids, manifests, and the mock provider are
  reproducible, which makes golden-transcript regression testing possible.
- **Lazy imports**: heavy/optional dependencies (PDF, embeddings, providers) are
  imported only when used, so the base CLI stays fast and dependency-light.
- **Evidence vs. truth**: the research stack records evidence; status upgrades
  are human-gated and "formally verified" requires a machine-checked proof.
- **Orchestration vs. mathematics**: a campaign can finish without solving the
  problem. Campaign state (phases, branches, obligations, budgets) lives in the
  campaign log; the problem's status is derived from dossier artifacts and is
  never copied into or inferred from campaign state.
- **Routing is recorded, never silent**: the model that answers a task is the
  one the pool leased for it, and both ledgers say which one and why.

See [artifact-model.md](artifact-model.md) for the persisted schemas and
[safety.md](safety.md) for the permission and egress guarantees.
