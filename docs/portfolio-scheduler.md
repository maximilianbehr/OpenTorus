# Portfolio, scheduler and failure memory

How a campaign decides *what to try* and *what to try next*. Everything on this page
is orchestration: none of it can change a claim status or the problem's status, which
stay derived from dossier artifacts (`opentorus problem verdict`).

Modules: `opentorus.campaign.portfolio`, `scheduler`, `failures`, `reallocation`,
`workers/*`, `research_bridge`, `importer`.

## Portfolio (GENERATE_PORTFOLIO)

```
proposals ──> dedup ──> cap ──> activation ──> events
 (template     REPEATED  PORTFOLIO  top max_active   branch_proposed / branch_rejected /
  or LLM)      _STRATEGY _CAP       by priority      branch_activated (+ APPR-* card)
```

* **Proposals.** With the mock provider (or no runtime) the *template* is used: the
  mode's fixed recipe rendered with the dossier's `STRATEGY_TEMPLATES` text.

  | mode | recipe (kind / root relation), in order |
  |---|---|
  | prove-or-refute | proof_sketch → proof/equivalent · counterexample_search → counterexample/counterexample-route · literature_map → literature/supporting · formalization_attempt → formalization/equivalent · special_cases → special-case/special-case (parent = the proof branch) · obstruction_search → obstruction/supporting · symbolic_simplification → symbolic/supporting |
  | exploration | numerical_experiment → numerical/supporting · counterexample_search · literature_map · special_cases |
  | survey | one literature branch per critical coverage category (`Cover the '<category>' literature …`), then one synthesis branch |

  The template proposes `initial_branches + 3` strategies so the cap has a real
  surplus to record. With a real provider the strategist (task class
  `campaign_strategy`, one routed model turn) is asked for a JSON array of
  `{title, kind, objective, strategy_summary, root_relation, assumption_context,
  why_distinct}`; the answer is parsed leniently, invalid items are noted, and fewer
  than two usable proposals fall back to the template (recorded in the phase outcome).
* **Priority** is `1.0 − 0.1·index` in proposal order (clamped at 0).
* **Dedup.** Same `(kind, root_relation)` and token-set Jaccard ≥ 0.8 on the
  normalised objective → `branch_rejected` with `REPEATED_STRATEGY` and
  `duplicate_of`; survivors carry a `distinctness_note`. Rejected proposals stay in
  the log (status `rejected`), never discarded.
* **Cap.** The first `initial_branches` survivors are kept, the rest are rejected
  `PORTFOLIO_CAP`. Mandatory branches always survive: prove-or-refute keeps a proof
  *and* a counterexample route; a literature branch is forced while any critical
  coverage category is insufficient. When the mandatory set is larger than the cap
  it is kept anyway (noted).
* **Activation.** The top `max_active_branches` by priority (tie-break `branch_id`)
  are activated; mandatory branches are swapped in for the lowest slots. The rest stay
  `proposed` (queued) and are activated in REALLOCATE when a slot frees up.
* Every accepted template branch gets a dossier `Approach` (`APPR-*`) recorded as an
  `artifact_created`.

## Scheduler (SCHEDULE)

A **documented heuristic, not a probability model**: every factor is visible in the
`ScoreBreakdown` of `work_item_scheduled` and reweightable via
`campaign.scheduler_weights`.

| factor | value |
|---|---|
| `root_impact` | equivalent 1.0 · counterexample-route 0.9 · sufficient 0.8 · necessary 0.5 · supporting 0.4 · special-case / relaxation 0.3 · unknown / unrelated 0.2 |
| `info_gain` | `1 / (1 + completed work items of the branch)` |
| `resolve_chance` | fixed kind × mode table (`scheduler.RESOLVE_CHANCE`) |
| `verifier_readiness` | 1 when the branch holds an artifact awaiting verification (gap-free proof attempt / counterexample candidate / unverified `PROOF-*`), else 0 |
| `novelty` | `0.5 ** (work items so far)` |
| `dependency_criticality` | `1 + 0.5 · number of branches depending on it` |
| `cost` | `estimated_cost / branch_step_budget` (0 when unlimited) |
| `redundancy` | max Jaccard of the objective against every other active branch |
| `failure_risk` | `min(1, consecutive_failures / 3)` |
| `fairness` | 1 when the branch has no more work items than the least-worked active branch |
| `literature_boost` | 1 for literature branches while coverage is insufficient (or in survey mode) |

`total = w_root·(root_impact + info_gain + resolve_chance)/3 + w_ver·verifier_readiness
+ w_nov·novelty + w_dep·dependency_criticality + fairness + literature_boost
− w_cost·cost − w_red·redundancy − w_fail·failure_risk`; ties break by `branch_id`,
then work item id. Runnable = active, branch step budget left, campaign step budget
left, dependencies completed. Fairness + novelty spread the first round over distinct
branches (a test asserts the first three work items span three branches).

## Failure memory (SCHEDULE / REALLOCATE)

* Every worker failure is a `FailureSignature` (`FSIG-*`, `failure_signature_recorded`).
  Its `key` is a sha256 over the normalised `(strategy_class, target_obligation,
  sorted assumption_context, tool_or_solver, error_category, counterargument)` — never
  over artifact ids or occurrence counts. A repeat of a known key reuses the signature
  id and bumps `occurrences`.
* **Retry gate.** Before a work item is scheduled on a branch whose latest work item
  failed, the engine computes what changed since that signature (`RetryChanges`:
  assumptions, target obligation, new theorem references, new evidence, solver,
  parameter regime, verification backend, human override — all from the snapshot and
  derived dossier facts). Nothing changed → `retry_refused`
  (`REPEATED_IDENTICAL_FAILURE`) and the branch is **suspended** with reactivation
  conditions; something changed → `retry_allowed` and `why_different` is appended to
  the signature's `retry_notes`.
* **Suspension** also happens in REALLOCATE for a branch with ≥ 2 trailing identical
  failures. Reactivation conditions follow the category: `verification_backend_changed`
  for `tool_unavailable` / `verifier_*`, `new_evidence_count` for `no_witness_found` /
  `model_no_progress`, `theorem_ref_accepted` for `citation_invalid`, `campaign_resumed`
  for `provider_unavailable` (the next `campaign resume` after the suspension is the
  signal that the endpoint is back), `human_override` otherwise — each recording what
  was observed at suspension.
* **Reactivation** (`branch_reactivated`) happens only when a *recorded* condition is
  met by the current facts (enabled verifier backends, evidence count, accepted
  theorem references); a campaign whose remaining branches are all suspended completes
  with the mode's "no runnable branches" criterion — nothing is retried on hope.
* **Exhaustion** (`branch_exhausted`, `BRANCH_EXHAUSTED`) when a branch spent its
  `branch_step_budget`.

## Workers

Each worker sees a frozen `WorkerContext` (ids, verified/accepted shared artifacts,
its own branch's artifact ids, budget, allowed tools, its own session id — never a
transcript) and returns a `WorkerResult`. Model-driven roles run a bounded `AgentLoop`
through the provider pool (routing recorded, usage tagged with campaign / branch /
work item / role) on a registry restricted to the role's tools. Offline behaviour under
the mock provider is deterministic and honest:

| role | mock provider | real provider |
|---|---|---|
| prover | 5 chat turns, then the `proof_write` bootstrap → a scaffold sketch with a gap; each explicit gap becomes an obligation proposal (referee / formal / SMT / sympy closure modes); a gap-free sketch proposes a whole-proof obligation. Only an `equivalent` branch writes the primary sketch; every other relation (special-case, relaxation, sufficient, necessary, …) is gate-coerced to *exploration* sketches with a bridge, never the dossier's primary answer, and its obligations come from its own sketch. Later attempts run in gap-fill mode; no `proof_write` → `model_no_progress` |
| falsifier | scaffolds and runs the `counterexample_search` template once per branch. An **unmodified** template tests a tautology, so — like `research.evidence.add_evidence`, which refuses to cite it — no evidence is recorded and the item fails `no_witness_found` saying why; an edited predicate is parsed and recorded through `record_search_evidence` (a witness = strong contradicting evidence, status untouched) | model designs the search (`exp_new` → edit → `exp_run`); every new experiment is parsed |
| numerical-experimenter | same rule with the `numerical` / `validated_numerics` template (`model_no_progress` when unmodified); edited experiments → `record_bounds_evidence` or weak neutral experiment evidence | model designs the computation |
| symbolic-experimenter | a `certificate: {json}` marker in the objective is submitted to the sympy backend (`PROOF-*` + verification recorded; rejected → `verifier_rejected`); no certificate → `verifier_inconclusive` "no symbolic certificate available for this objective" | model produces and submits certificates |
| formalizer | no lean/coq/smt backend → `tool_unavailable` (records the enabled backends); backend but mock → `verifier_inconclusive` (no formal source) | model formalizes and calls `proof_submit`; every submission recorded |
| critic (CRITIQUE phase) | `agent.review.review_target` on the round's new workspace claims + `dossier.referee.referee_review(persist=True)` on new dossier claims / proof attempts → `review_requested` / `review_recorded`; downgrades are never applied | same (deterministic by design) |
| librarian | parses unread local PDFs (bounded), extracts heuristic THMREF candidates (attributed to the problem), coverage assessment (≤ partial), `branch_done` | — |
| verifier-coordinator (VERIFY) | closure proposals only for accepted artifacts | — |
| synthesizer | progress + report; `branch_done` on a survey synthesis branch | — |
| strategist | template | JSON proposals |

Target claim for evidence: the dossier's designated primary claim when there is one,
else one branch-level workspace claim (`research.claims.new_claim(problem_id=…)`)
recorded as `artifact_created` and stored on the branch (`target_claim_id`).

## `research` façade and the importer

`opentorus research` writes exactly what it always wrote. With `--campaign` (or
`campaign.record_research: true`) *and* an attributed problem, the run is also
mirrored into an exploration campaign under that problem: `imported_from:
research:<slug>`, one numerical branch "Autonomous research: <question>", one work
item per iteration with the EXP / EVIDENCE / CLAIM ids as artifact references, walked
through the real phase machine, completed when the run stops (`research run stopped:
<reason>`); an interrupted run leaves it resumable at SCHEDULE.

`opentorus campaign import-research QUESTION | --slug SLUG [--problem P] [--force]`
converts a legacy run the same way, replaying its journal entries and stamping
provenance as the first event after creation (`migration_recorded`: source paths,
sha256s, import time, importer version). The research state, journal and progress note
are read, never modified; a second import is refused unless `--force`.
