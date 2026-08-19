# Model routing

Which model answers for which task, and how you can tell afterwards. Modules:
`opentorus.providers.pool` (profiles, routes, the pool, the routing ledger),
`opentorus.providers.capabilities` (what a profile can do, the probe cache),
`opentorus.config` (`ModelsConfig`, `RoutingConfig`), `opentorus.usage`
(provenance fields on every usage row), `opentorus.doctor` (the checks).

Before the campaign engine, `governance.route_model` returned a model *name*
that nothing acted on: the provider was built once from `model:` and the usage
ledger recorded the configured name. Routing is now real -- the provider that is
leased for a task class is the one that answers -- and auditable: every lease
appends a record, every usage row says which profile was requested, which was
selected, and which model the API actually reported.

The single-model configuration you already have keeps working unchanged: with
routing disabled the pool leases the implicit `default` profile, which is
exactly the provider `get_provider(config)` built before.

## Profiles

A **profile** is a named `model:` block. The `model:` block itself is always
available as the implicit profile `default`; `models.profiles` adds more, and
`models.default_profile` may name one of them to use when no route applies.

| key | meaning |
|---|---|
| `models.default_profile` | `null` (the `model:` block) or the name of a profile below |
| `models.profiles.<name>` | every `ModelConfig` field -- `provider`, `name`, `temperature`, `base_url`, `timeout_seconds`, `num_ctx`, `top_p`, `top_k`, `seed`, `num_predict`, `max_tokens`, `keep_alive`, `verify_tool_calling` -- plus two profile-only keys |
| `models.profiles.<name>.capabilities` | declared capabilities (list; see below). Needed for tool calling on Ollama models, which the provider kind cannot guarantee |
| `models.profiles.<name>.local_only` | `true` / `false` overrides the local-vs-cloud classification (`null` = derive it from provider kind and `base_url`) |

A profile is built into a provider through the ordinary factory on a
profile-derived config (`pool.profile_config`), so it behaves exactly like a
`model:` block would -- timeouts, sampling, Ollama options and the tool-calling
check included. Providers are built lazily and cached per profile for the life
of the pool.

## Routes

| key | meaning |
|---|---|
| `governance.routing.enabled` | `false` (default): every task class uses the default profile |
| `governance.routing.task_routes` | task class -> **ordered list** of profile names; the first eligible profile answers, the rest are fallbacks. `default` is the fallback route for every class |
| `governance.routing.task_models` | the legacy form (task class -> bare model name, run on the default profile's provider), still honoured, including its `"default"` fallback; the legacy names `proof`, `critique`, `planning` map onto `proof_development`, `adversarial_critique`, `campaign_strategy` (and back) |

Candidate order for a task class `tc` (`ProviderPool.candidates`):

```
task_routes[tc]  ->  task_routes["default"]  ->  task_models[tc]  ->  task_models["default"]  ->  default profile
                     (each legacy entry becomes the synthesised profile "default@<model>")
```

With routing disabled the list is the default profile only. In every case, if
`models.default_profile` names a profile that does not exist, the implicit
`default` (the `model:` block) is appended as the last candidate so a typo does
not fail every command -- the fallback is recorded (see below) and `doctor` flags
it.

### The task classes

Sixteen classes plus `default` (`pool.TaskClass`). What uses each today:

| task class | used by |
|---|---|
| `campaign_strategy` | the campaign strategist (portfolio proposals); legacy alias `planning` |
| `proof_development` | `opentorus prove`; the campaign prover; legacy alias `proof` |
| `counterexample_search` | the falsifier |
| `literature_synthesis` | the librarian |
| `symbolic_experiment_design` | the symbolic experimenter |
| `numerical_experiment_design` | the numerical experimenter |
| `formalization` | the formalizer |
| `adversarial_critique` | the critic; legacy alias `critique` |
| `verification_support` | the verifier-coordinator's work items (which make no model call today); the class a model-written `proposed_analysis` on an applicability check is routed under |
| `final_synthesis` | the synthesizer |
| `theorem_extraction` | `opentorus theorem extract --llm` |
| `narration` | `opentorus research` (its narration turns) |
| `problem_normalization`, `portfolio_deduplication`, `scheduling`, `code_generation` | reserved: normalization, de-duplication and scheduling are deterministic today and make no model call; the classes exist so a route can be configured before a caller does |
| `default` | the fallback route |

`opentorus run` and `opentorus chat` still build the provider directly from
`model:` (they are not task-classed).

## Capabilities and the probe cache

`ProviderCapability`: `tool_calling`, `streaming`, `structured_output`, `vision`,
`large_context`, `local_only`, `formalization_support`, `json_schema`.

A profile's effective capabilities are the union of three sources
(`capabilities.effective_capabilities`) -- **acquire never probes online**:

1. **static** -- what the provider *kind* guarantees (`STATIC_CAPABILITIES`:
   OpenAI and Anthropic chat models call tools and see images; the mock is local
   and calls tools; Ollama streams and is local). Ollama tool calling is
   deliberately not static because it depends on the pulled model;
2. **declared** -- the profile's `capabilities:` list;
3. **cached probes** -- `.opentorus/providers/capabilities.json`, keyed
   `provider|model|base_url`, written only by `opentorus doctor --probe`.

`local_only` is added when the profile runs locally (mock, ollama, or a
loopback / private `base_url`) and removed by an explicit `local_only: false`, so
a private-looking endpoint that tunnels to a cloud API can be labelled honestly.

```
opentorus doctor --capabilities            # per-profile capability tables, route fallback availability
opentorus doctor --capabilities --probe    # + one model call per non-mock profile, result cached
opentorus doctor --json                    # every check as {name, ok, detail, data}
```

`--probe` implies `--capabilities`. The probe can confirm tool calling or stay
inconclusive, never deny it; an inconclusive probe caches an empty record with the
reason. The doctor checks added with routing are `profiles` (every resolvable
profile, its provider/model, credential env-var *name* and whether it is set,
capabilities), `routes` (candidates per task class, unknown profile names, whether
a fallback exists), `credentials` (missing env-var names, never values),
`formal-systems`, `dashboard`, `paper-parsing`, `dossier-state` (writable, and
campaigns with their replay diagnostics), `version`. An absent optional backend is
`ok` and informational; what fails a check is an unknown profile name in a route,
an unknown `models.default_profile`, an unknown provider kind or capability name
on a profile, or a missing credential for a profile some route can reach.

## Eligibility, fallback, and refusal

`ProviderPool.acquire(task_class, required_capabilities=frozenset(),
budget_context=None, *, tags=None) -> ProviderLease` walks the candidates in
order and takes the first that is **eligible**: the profile exists, its provider
kind is known, it has every required capability, it is local when the caller
requires local-only, its per-provider budget (`governance.budgets.per_provider_usd`)
is not breached, and -- when the caller's cost budget is spent -- it is local.

- **Fallback is never silent.** When the first candidate was skipped, the
  record's `fallback_reason` names every skipped profile and why (`'strong'
  skipped: missing capabilities: vision; ...`), and `candidates_considered` keeps
  the per-profile verdict. An undefined `models.default_profile` adds
  `models.default_profile '<name>' is not defined; using the implicit default
  profile` in plain words.
- **Refusal is recorded too.** When no candidate is eligible the record is
  written with `outcome="no_eligible_provider"` and `NoEligibleProviderError`
  (a `ProviderError`) is raised carrying the verdicts. Callers report it like any
  provider failure; a campaign worker turns it into a failure signature. Nothing
  quietly uses a provider that a budget or a capability check ruled out.

## The routing ledger

Every acquire -- with or without routing enabled, in `prove`, `research`,
`theorem extract --llm`, and every campaign worker -- appends a
`RoutingDecisionRecord` to **`.opentorus/usage/routing.jsonl`**:

| field | meaning |
|---|---|
| `decision_id` | `RTD-NNNN`, workspace-sequential (`next_id` over the ledger) |
| `task_class` | what the call was for |
| `requested_profile` | the first candidate |
| `selected_profile` | the profile that answered (`null` on refusal) |
| `provider`, `configured_model` | the selected profile's provider kind and configured model id |
| `actual_model` | the model the API reported, back-filled from an observation line |
| `required_capabilities` | what the caller demanded |
| `candidates_considered` | `[{profile, eligible, reason}]` in the order tried |
| `fallback_reason` | why the first candidate was not used (`null` when it was) |
| `routing_enabled`, `local_only_required` | the switches in force |
| `created_at` | from the pool's clock (the campaign's `StepClock` under test) |
| `campaign_id`, `branch_id`, `work_item_id`, `session_id` | attribution when known |
| `outcome` | `selected` or `no_eligible_provider` |

The ledger is append-only and mixes two line shapes: decisions, and
**observations** (`{decision_id, actual_model, observed_at}`) appended by
`pool.note_actual_model` when a response names its model; `read_routing_ledger`
folds observations into their decisions. Corrupt lines are skipped with a
warning like every other ledger.

### Provenance on every usage row

`UsageRecord` (`.opentorus/usage/ledger.jsonl`) gained: `routing_decision_id`,
`requested_profile`, `selected_profile`, `configured_model`, `actual_model`,
`fallback_reason`, and the campaign attribution `campaign_id`, `branch_id`,
`work_item_id`, `worker_role`. `provider` and `model` now name the provider that
actually answered (`BaseProvider.model_name`, `ProviderResponse.model`), not the
workspace default. `usage.read_usage(ot_dir, campaign_id=...)` and the
campaign-scoped governance budgets read the same rows; the decision id is the
join key between the two ledgers.

## Privacy and egress

Everything above is local: both ledgers live under `.opentorus/usage/`, the probe
cache under `.opentorus/providers/`, and none of it is sent anywhere. Credentials
are referred to by environment-variable name only. Which provider a turn goes to
decides what happens to the bytes: the pre-egress DLP scan, cost estimation
(`$0 (local)`), the tool-calling check and Ollama's forced `tool_choice` are all
decided from the **leased** profile, never from the workspace `model:` block, so a
cloud lease under a local default profile is screened and priced as a cloud
call. See [privacy.md](privacy.md) and [safety.md](safety.md).

## Configuration example

Placeholders only; there are no model names in this file on purpose.

```yaml
model:                                   # the implicit profile "default"
  provider: <provider>
  name: <model-id>

models:
  default_profile: null                  # null = the model: block above
  profiles:
    strong:
      provider: <provider>
      name: <model-id>
      capabilities: [tool_calling]       # declare when the provider kind cannot guarantee it
    fast:
      provider: <provider>
      name: <model-id>
      base_url: <optional endpoint url>
      temperature: 0.1
    local:
      provider: ollama
      name: <model-id>
      base_url: http://127.0.0.1:11434
      capabilities: [tool_calling]
      local_only: true

governance:
  routing:
    enabled: true
    task_routes:
      proof_development: [strong, default]
      adversarial_critique: [strong, local]
      narration: [fast, local]
      theorem_extraction: [strong]
      default: [local]                    # the fallback route for every other class
    task_models: {}                       # legacy form; still honoured when present
```

With this file, `opentorus prove PROBLEM-0001` leases `strong` for
`proof_development` (falling back to `default` if `strong` is ineligible), a
campaign's critic leases `strong` then `local`, `opentorus research` narrates on
`fast`, and every other class tries `local` first, then the default profile.
`opentorus doctor --capabilities` shows the resolved candidates per class and
whether each has a fallback.

## Limitation: `config set` cannot write mappings

`opentorus config set` writes scalar leaves. `models.profiles` and
`governance.routing.task_routes` (and `task_models`) are mappings and must be
edited in `.opentorus/config.yaml` by hand; `doctor` says so whenever a route
names an unknown profile or no route is configured. `write_config` does expand an
empty one-line container (`profiles: {}`, `task_routes: {}`) into a block when the
loaded config carries values under it, and warns by name about any leaf it could
not place under a hand-written flow container -- nothing is silently dropped.
