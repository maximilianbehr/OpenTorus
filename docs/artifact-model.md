# Artifact Model

Everything OpenTorus produces is a **typed artifact** persisted under
`.opentorus/`. Artifacts are validated with [`pydantic`](https://docs.pydantic.dev/),
serialized as append-only JSONL or per-artifact YAML, given **deterministic
ids**, and connected through a typed graph. This is what makes a loop
inspectable: you can always trace a conclusion back to its evidence.

## Layout

```
.opentorus/
  config.yaml            # configuration
  session.jsonl          # interactive/agent turns (SessionMessage)
  actions.jsonl          # ActionLogEntry: tool, args, permission decision, outcome
  MEMORY.md              # consolidated memory index (`memory consolidate`), shown as data
  memory/                # structured memory (facts, decisions, hypotheses, …)
    session_summaries.jsonl  # SessionSummary per session / finished campaign (stage one)
    consolidations.jsonl     # ConsolidationRecord: published / rejected / unchanged
    citations.jsonl          # CitationRecord: entry cited by a session (once per pair)
    exposures.jsonl          # ExposureRecord: entry shown to a session (once per pair)
    MEMORY.md.prev           # the MEMORY.md a publish replaced
  skills/<name>/SKILL.md # project skills (front matter: name, description)
  claims.jsonl           # Claim
  evidence.jsonl         # EvidenceEntry (contradictions preserved)
  graph.jsonl            # GraphEdge (typed relations)
  experiments/EXP-*/     # run.py, results/ (stdout, stderr, manifest.yaml), summary.md
  papers/PAPER-*/        # metadata + cached full text / notes
  datasets/DATASET-*/    # metadata: hash, license, source
  repos/REPO-*/          # metadata (pinned commit, license, test outcome)
  problems/PROBLEM-*/     # math dossiers (statement, claims, report.md, …)
    campaigns/CAMPAIGN-*/  #   campaign.yaml, events.jsonl, snapshot.json, progress.md, branches/
  theorems/              # THMREF references, relations, applicability checks, coverage/
  providers/capabilities.json   # doctor's probe cache (provider|model|base_url -> capabilities)
  proofs/PROOF-*/        # formal proof attempts (Lean/Coq/SMT)
  formal_statements.jsonl  # FormalStatement (FSTMT-*): frozen formal statements of claims
  formal_statements/     # FSTMT-*.lean / .v frozen source files
  reviews/REVIEW-*/      # critic reviews and findings
  figures/FIGURE-*/      # reproducible figures (script, data hash, seed)
  drafts/                # LaTeX/BibTeX paper drafts
  index/                 # hybrid BM25 + embedding index
  journal/               # research-loop journal entries
  research/              # research-loop checkpoints/state
  usage/ledger.jsonl     # estimated token/cost ledger (UsageRecord)
  usage/routing.jsonl    # routing decisions (RoutingDecisionRecord) + actual-model observations
```

## Core artifacts

| Artifact | Id prefix | Purpose |
|----------|-----------|---------|
| Claim | `CLAIM-` | A research statement with an explicit status. |
| Evidence | (in `evidence.jsonl`) | A supporting/contradicting observation linked to a claim. |
| Experiment | `EXP-` | A reproducible run folder with a captured manifest. |
| Paper | `PAPER-` | A registered/cached source with provenance. |
| Dataset | `DATASET-` | An acquired dataset, hash + license pinned. |
| Repo | `REPO-` | External code at a pinned commit; test runs as evidence. |
| Problem dossier | `PROBLEM-` | Scoped open problem with claims, evidence, and honest report. |
| Proof | `PROOF-` | A formal proof attempt and its backend outcome. |
| Frozen formal statement | `FSTMT-` | The exact Lean/Coq theorem a proof of one claim must prove; sha256-digested, human-accepted. |
| Patch | `PATCH-` | A proposed edit (applyable / revertable). |
| Review | `REVIEW-` | A critic review with structured findings. |
| Figure | `FIGURE-` | A regenerable plot with provenance. |
| Campaign | `CAMPAIGN-` | A persistent portfolio campaign on one dossier: event log + derived snapshot (orchestration only). |
| Theorem reference | `THMREF-` | A located, reviewable pointer to one numbered result in a local paper (`THMREL-` relations, `THMAPP-` applicability checks, `COV-` coverage assessments). |
| Routing decision | `RTD-` | Which model profile was leased for a task class, and why. |

Workspace-global claims, evidence, and experiments carry an optional `problem_id`,
stamped from the active problem when the agent creates them, so `problem show`
reports per-dossier counts. Records created outside any active problem (or before
attribution existed) leave `problem_id` unset and are reported as unattributed.

## Claims and the status ladder

Claims never auto-promote. They move up a deliberate ladder, and the stronger
statuses are *restricted* (explicit human confirmation required):

```
idea → observation → evidence → hypothesis → partially_validated
     → human_reviewed → verified
```

with `refuted` as a terminal outcome, plus research-specific statuses
(`conjecture`, `numerical_evidence`, `proof_sketch`, `formally_verified`). The
central rule: **experiments are evidence, not verification.** `verified` /
`formally_verified` require a real, reviewable (or machine-checked) proof.

## Evidence ledger

Each `EvidenceEntry` links a source artifact to a claim with a **direction**
(`supports` / `contradicts`) and a **strength**. Contradictory evidence is
preserved, never overwritten — the ledger is an honest record, not a verdict.

## The artifact graph

`GraphEdge` records typed relations between artifacts (e.g. `tests`, `cites`,
`derived_from`, `supports`, `contradicts`, `weakens`). `opentorus graph show`
renders it; `opentorus explain <id>` walks a focused subgraph to show how an
artifact is supported, encoding each node's rigor/status.

## Reproducibility metadata

Every experiment writes a `ResultManifest`: command, exit code, environment,
git commit, random seed, and — when run in a container — the pinned
`image_digest`, cache key, and cache-hit flag. `opentorus exp replay` re-runs
from the manifest and reports any divergence.

## Provenance & honesty

Artifacts carry provenance (where a paper/dataset/repo came from, which commit,
which license). Reports and drafts may only cite artifacts that exist locally,
and the honesty linter flags language that overclaims relative to an artifact's
actual rigor.

## Dossier claim ledger

The per-problem dossier uses its own typed `ClaimRecord` ledger (distinct from the
workspace-global claims ladder above). A claim carries a `type` and a `status`:

- **types:** `OBSERVATION`, `CLAIM`, `CONJECTURE`, `LEMMA_ATTEMPT`, `THEOREM`,
  `COUNTEREXAMPLE_CANDIDATE`, `COUNTEREXAMPLE_VERIFIED`, `REFERENCE_FACT`,
  `FORMAL_PROOF_VERIFIED`, `FORMAL_PROOF_FAILED`, plus `HEURISTIC` (a plausibility
  argument, never claimed proven), `EXPERIMENTAL_OBSERVATION` (a regularity read
  off experiments), and `OPEN_GAP` (an explicitly tracked unresolved
  sub-question). `DEFINITION` and `ASSUMPTION` remain separate record types.
- **statuses:** `unverified` → `supported` → (`contradicted` / `refuted` /
  `needs_review`) and the verified tier `verified` / `formally_verified`. New
  types default to `unverified`; `needs_review` is a review flag and never
  requires a verification artifact. The verified tier still requires one — adding
  these values does not weaken EVAL-001/EVAL-002.

### What "a verification artifact" means

`FORMAL_PROOF` and `VALIDATED_NUMERICAL` are the two verification-grade evidence types
(`epistemics.VERIFICATION_EVIDENCE`); every other type is support-only. Being
verification-grade is a property of the *artifact*, not of the type name: recording
either kind requires citing a `PROOF-*` attempt in this workspace's proof ledger that a
backend **accepted**. A hallucinated id, a rejected attempt, and an inconclusive one
(timeout, crash, unreadable source) are each refused, naming which.

This is what makes EVAL-002 enforceable rather than declarative. Checking only the type
field meant `problem evidence --type FORMAL_PROOF`, with nothing behind it, satisfied
the verification check and unlocked `formally_verified`.

The same distinction runs through the verifier backends: a result is `accepted`,
`rejected`, or `inconclusive`, and only the first two are statements about the
mathematics. A solver timeout or an `unknown` verdict, a prover killed by a signal, and
an interval enclosure too coarse to settle the question are all `inconclusive` — "the
check did not conclude", never "the claim is false".

### The Lean/Coq acceptance gate

Exit code 0 is necessary, never sufficient: Lean exits 0 on a file full of `sorry`, Coq
on one ending in `Admitted`. A Lean/Coq `PROOF-*` is `accepted` only when
(`research/verifiers/backends.py`, `lean_rules.py`, `coq_rules.py`):

1. a textual pre-scan, *before anything runs*, finds none of `sorry`, `native_decide`,
   a user `axiom`, `set_option pp.*`/`debug.*`, or a code-execution / syntax-extension
   word (`#eval`, `#exit`, `run_cmd`, `run_elab`, `macro`, `elab`, `syntax`,
   `notation`, `initialize`, `implemented_by`, `extern`, `unsafe`, `IO`, `Lean.*` …;
   Coq: `Admitted`, `admit`, `Axiom`, `Parameter`, `Declare ML Module`, `Load`,
   `Unset … Checking` …) outside comments and strings. Constructs the lexer cannot
   read unambiguously (interpolated/escaped strings, unclosed comments) are refused;
2. the checker runs under `bwrap` without network, with a read-only filesystem and only
   its temp dir writable (`tools.verifiers.confine`: `auto` — when bwrap works,
   `require` — refuse without it, `off`); the attempt records `confined`;
3. the gate appends `#print axioms <thm>` for every declared `theorem`/`lemma` (Coq:
   `Print Assumptions`) behind a fresh random marker and reads *only* the output after
   it: every theorem's axioms must be within {`propext`, `Classical.choice`,
   `Quot.sound`} (Coq: closed under the global context), with no `sorryAx`. A file with
   no identifiable theorem (only `example`s) is rejected — fail closed.

The checker is `tools.verifiers.lean_command` (`lake env lean <file>`) or, with
`tools.verifiers.lean_repl: true`, a resident leanprover-community/repl process with
`lean_repl_header` (`import Mathlib`) elaborated once (`verifiers/lean_repl.py`:
per-request deadline, kill on timeout, a single respawn on death — both inconclusive,
never rejections). Only how Lean runs changes; the gate reading its output is the same.

Setting up Lean with Mathlib (verified on Lean v4.36.0-rc1 / Rocq 9.2):

```bash
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
  | sh -s -- -y --default-toolchain none          # puts lake/lean in ~/.elan/bin
lake +leanprover-community/mathlib4:lean-toolchain new ~/lean/mathlib-env math
cd ~/lean/mathlib-env && lake exe cache get && lake build
```

`lake env lean` resolves the project from the current directory, so point the
checker at the project explicitly: `lean_command: env -C ~/lean/mathlib-env lake env
lean` (with `~/.elan/bin` on PATH). For the REPL, build leanprover-community/repl at
the project's toolchain tag and use `lean_repl_command: env -C ~/lean/mathlib-env lake
env ~/lean/repl/.lake/build/bin/repl`. On a 16 GB machine a cold `import Mathlib`
takes 1.5–2.5 minutes per check with or without bwrap; the resident REPL pays that
once and then checks in ~0.1 s. `pytest -m integration tests/test_real_provers.py`
with `OPENTORUS_LEAN_PROJECT` set runs the gate against the real checkers.

A gate refusal is recorded with a machine-readable `rejection` (`sorry`,
`forbidden_token`, `nonstandard_axioms`, `no_theorem`, `no_report`, `elaboration`,
`statement_mismatch`, `preamble_mismatch`, `type_mismatch`); `axioms`, `theorem` and
structured `diagnostics` (error classes, first error, unsolved goal) are stored beside
the verbatim output.

### Frozen formal statements and statement fidelity

An accepted Lean file proves *some* theorem; nothing ties that theorem to the claim
it is cited for. A `FormalStatement` (`FSTMT-*`, `formal_statements.jsonl`) is a
complete frozen file — preamble (imports, opens, definitions), exactly one theorem, and
the placeholder proof `sorry` (Coq: `Admitted`) — bound to one claim (`claim_id`, plus
`problem_id` for a dossier claim), with the source's `sha256`. It is `proposed`
(`opentorus proof statement add FILE --claim CLAIM-…`) and binds nothing until a human
`accept`s it (`opentorus proof statement accept FSTMT-…`, interactive confirmation; the
digest is re-checked against the file at acceptance). Accepting a new statement retires
the previous one for that claim and backend.

A `proof_submit` against a claim with an accepted statement must contain the statement
verbatim (whitespace-normalized, outside comments), begin with the frozen preamble (the
checked file is rebuilt as *frozen preamble* + separator command + the candidate's
remainder, so definitions cannot be redefined or continued), and elaborate the theorem
to the same type as the frozen statement checked with `sorry` (`#check @thm` under
`pp.all`, the "pristine type", cached on the FSTMT record per checker version). Such a
proof is recorded with `statement_bound: true` and `statement_id`.

**Only a statement-bound Lean/Coq proof promotes a claim** (`proofs.can_promote`): the
workspace ladder (`formally_verified`) and dossier `FORMAL_PROOF` evidence both refuse an
accepted but unbound one, naming the reason; its graph edge is `supports`, not
`validates`. Lean/Coq proofs recorded before this rule carry `statement_bound: false`
and no longer promote. SMT and the certificate checkers are not covered by frozen
statements (they keep their earlier rules).

A ``PROOF-*`` record carries two dossier references, and they answer different
questions. `problem_id` says which claim *store* its `claim_id` belongs to — the
workspace ladder and each dossier share the `CLAIM-NNNN` space, so an unqualified id is
ambiguous. `submitted_under` says which campaign produced the submission, and is what
the referee's formalization demand is scoped by. Keeping them apart matters: the agent's
`proof_submit` targets workspace claims and so carries no `problem_id`, so scoping the
demand by that field instead would never let any agent submission clear it. Records
written before provenance existed carry neither, and count only in a workspace holding a
single dossier, where there is nothing to confuse them with.

A verdict is also discarded when the solver printed `(error …)` alongside it. z3 and
cvc5 do not abort on a malformed assertion: they drop it and solve what remains, so the
verdict describes a different problem than the one submitted. This matters in both
directions — a `sat` there is not a refutation, and an `unsat` there is not a proof,
which is the more dangerous of the two given that an accepted proof is the one artifact
that can promote a claim to `formally_verified`.

A claim type may only ever be **weakened** programmatically
(`downgrade_claim_type`, e.g. `THEOREM → CONJECTURE`), which sets the status to
`needs_review` and logs the change; promotion to a settled result still requires
the verification CRUD.

## Report status gate

`status_gate.derive_status` derives, from the artifacts alone, a separate
**report status** — `SOLVED`, `PARTIALLY_SOLVED`, `HEURISTIC_ONLY`,
`EXPERIMENTAL_ONLY`, `UNSOLVED`, or `INVALID` — so a pile of proof sketches can
never read as a solution. It is additive and does not overload the dossier's own
`ProblemStatus`. The report header surfaces it (Status / Verified theorems /
Heuristics / Experiments run / Main gaps / Referee verdict / Recommended next
step).

## Referee

`referee.referee_review` is a hostile, deterministic post-proof stage. It
classifies every theorem-like claim (`proved` / `cited` / `heuristic` /
`unsupported` / `refuted`), recommends `THEOREM → CONJECTURE` downgrades for
claims that are neither proved nor cited, flags cross-claim contradictions, and
runs the honesty linter over every claim and proof body. It persists a
machine-readable `REFEREE-*.json` plus a human `.md` under `<dossier>/referee/`
and returns a `pass` / `revise` / `block` verdict. A reusable prompt lives at
`prompts/referee.md`.

During `opentorus prove` the referee also runs *in-loop* (without persisting a
record) the moment the model declares the sketch gap-free: a `block` verdict
reopens the proof's gap list with the referee's findings (each tagged
`[REFEREE]`), so the loop keeps working instead of accepting an overclaiming
"done". The run settles only when the proof is gap-free *and* the referee no
longer blocks. This is governed by `agent.prove_referee_reopens_gaps` (default
on) and is active only while `agent.prove_until_gaps_closed`; the no-progress
backstop still bounds a model that cannot satisfy the referee. The referee
remains record-only — it reopens gaps but never upgrades truth status.

## Gap-closure challenge

Every proof attempt stores an `evidence_snapshot` — the number of parsed papers
plus recorded experiments at the moment it was last written (the same "new work"
signal the prove loop's no-progress window uses). When a `proof_write` refines
the dossier's primary answer and would close **two or more numbered `[GAP-n]`
markers at once** with the snapshot unchanged — no new parsed paper, no new
experiment — the write is rejected with a challenge: gather the missing support
first, or close one gap per rewrite with the completed argument spelled out.
Closing a single gap by pure reasoning is always allowed; descriptive gap
entries without a `GAP-n` marker and referee-reopened `[REFEREE]` gaps are not
counted (the latter answer to the referee's own recheck, so rewording flagged
language is never blocked). Attempts recorded before the snapshot field existed
are never challenged. This enforces invariant 5 at the artifact boundary:
deleting gap markers is not closing gaps.

## Failed attempts as steering, not just record

`failed_attempts.jsonl` (`FailedAttempt`, with `reusable_obstruction`),
`problem.yaml:known_obstructions`, and workspace `failed_attempts` memory are
first-class artifacts (invariant 5) — and the prove loop reads them back. Every
proof prompt and every gap-recovery hint carries a "Known dead ends for this
dossier — do NOT retry these unchanged" block built from them (obstructions first,
reusable failed attempts before plain ones, at most twelve lines). Workspace
memory is attributed to a dossier only when the entry names its id, or when the
workspace holds a single dossier; the prompt therefore asks the model to log
routes that failed as `memory_add(kind=failed_attempts, text='PROBLEM-XXXX: <method>
— fails because <reason>')`. The block is a constraint, not a verdict — the model
may contest a recorded dead end if it says what changed and cites the artifact —
and it never touches any status.

## Experiment-citation integrity

An experiment citation must point at a real `EXP-*` manifest: citing an id that
was never created is rejected, and citing a real but not-yet-run experiment is
recorded with an advisory (its results do not exist yet). Both the dossier and the
workspace-global evidence paths enforce this, mirroring the `PAPER-*` citation
grounding.

## Campaign artifacts

A campaign lives under its dossier at
`problems/PROBLEM-XXXX/campaigns/CAMPAIGN-XXXX/` -- workspace-unique ids, one
directory per campaign:

| file | contents |
|---|---|
| `campaign.yaml` | `CampaignRecord`: id, `problem_id`, `mode`, `schema_version`, `created_at`, `statement_sha256`, the frozen `config_snapshot` (every budget as started; `0` = unlimited), `imported_from` / `migration_provenance`, `primary_claim_id`. Never rewritten. |
| `events.jsonl` | the append-only typed event log: `CampaignEvent{event_id (EVT-NNNNNN = seq), campaign_id, seq, schema_version, timestamp, type, actor, role, refs, payload, causation_id, correlation_id, work_item_id, branch_id}`; the payload of each type is a registered pydantic model. |
| `snapshot.json` | `CampaignSnapshot`: the pure reducer's fold of the log -- phase, status, branches (`BRANCH-NNNN`), work items (`WI-NNNN`), obligations (`OBL-NNNN`), failure signatures (`FSIG-NNNN`), the budget ledger, artifact *references*, routing decision ids, campaign proof-tree nodes, diagnostics, counters, phase history. Atomically rewritten, never ahead of the log; `campaign verify` recomputes it. |
| `progress.md`, `branches/*.md` | human-readable; nothing reads them back. |

**What is deliberately absent from the snapshot:** claim statuses and the root
mathematical status. They are read from the dossier when a view needs them, so
the campaign layer can never disagree with -- or quietly upgrade -- what the
dossier says. `campaigns/` is on the dossier's write-protected list
(`tools/filesystem._DOSSIER_MANAGED_ARTIFACTS`), so the agent's file tools
cannot edit these files. Details: [campaign-persistence.md](campaign-persistence.md).

### Obligations and the closure rule

An `Obligation` (`OBL-NNNN`) is a proof obligation a campaign opened -- typically
one per explicit `[GAP-n]` of a new sketch (`source_proof_id`, `gap_marker`) --
with a statement, assumptions, quantifiers, its `root_relation`, dependencies,
the closure modes it accepts, supporting / contradicting artifacts, review
findings, and a status (`open`, `in_progress`, `closed`, `contradicted`,
`abandoned`). It lives in the campaign event log; editing the proof body cannot
change it.

An obligation closes **only** through an `obligation_closed` event that cites an
artifact `proof_tree.settlement.can_close_obligation` accepted, in one of seven
modes: `formal_proof`, `smt_certificate`, `exact_symbolic_certificate`,
`validated_numerical_certificate` (an accepted `PROOF-*` in the verifier ledger,
passing the same four checks as `dossier.claims._require_verification_artifact`),
`accepted_counterexample_certificate` (a `COUNTEREXAMPLE_VERIFIED` claim naming
every recorded root assumption), `nl_proof_referee_accepted` (a gap-free primary
sketch the deterministic referee passes -- the weakest mode, not machine
verification), `accepted_literature_theorem` (an accepted `THMREF-*` with an
accepted applicability check). Deleting a gap marker closes nothing; closing an
obligation changes no claim status; special-case and relaxation obligations
never settle the root. See [proof-tree.md](proof-tree.md).

## Theorem-reference ledgers

Workspace-level, under `.opentorus/theorems/` (a theorem is a fact about a paper,
not about one dossier): `references.jsonl` (`TheoremReference`, `THMREF-NNNN`: a
local `PAPER-*`, a validated `SourceLocator`, `location_hash`, an excerpt of at
most 300 characters, the normalised statement, categories, `review_status`
`candidate` / `accepted` / `rejected`), `relations.jsonl` (`THMREL-NNNN`),
`applicability_checks.jsonl` (`THMAPP-NNNN`, result `accepted` / `rejected` /
`inconclusive` / `needs-human-review`), `coverage/PROBLEM-XXXX.jsonl`
(`COV-NNNN` assessments and human overrides). Extraction -- heuristic or LLM --
only ever produces `candidate`; `opentorus theorem review --status accepted` is
the sole path to `accepted`; only an accepted, problem-attributed reference
licenses `has_reference` in the report's honesty context. The per-dossier
`THM-*` refs (`problem theorem`) are untouched. See
[theorem-references.md](theorem-references.md).

## Usage and routing ledgers

`usage/ledger.jsonl` (`UsageRecord`) gained routing provenance and campaign
attribution: `routing_decision_id`, `requested_profile`, `selected_profile`,
`configured_model`, `actual_model`, `fallback_reason`, `campaign_id`,
`branch_id`, `work_item_id`, `worker_role`. `provider` and `model` name the
provider that actually answered. `usage/routing.jsonl` holds one
`RoutingDecisionRecord` (`RTD-NNNN`) per provider lease -- task class, requested
and selected profile, provider, configured and actual model, the per-candidate
verdicts, `fallback_reason`, `outcome` (`selected` / `no_eligible_provider`),
attribution -- plus append-only actual-model observations. Both are local, and
the decision id joins them. See [model-routing.md](model-routing.md).

## Consolidated memory and citations

`MEMORY.md` is one `- ` line per remembered thing, rewritten only by
`opentorus memory consolidate` (optionally at the end of `run` / `campaign` with
`memory.auto_consolidate: true`; off by default). Each line is addressed by a
content id `M-<8 hex>` (SHA-1 of its whitespace-normalised text), so a rewrite that
keeps a line keeps its id. Stage one writes one `SessionSummary` (`SUM-NNNN`) per
session id in `session.jsonl` and per finished campaign (`status` completed /
stopped / failed); an empty or rejected summary is kept too, so the source is not
re-read. Stage two writes one `ConsolidationRecord` (`CONSOL-NNNN`): `published`
(the file was replaced atomically, the old one saved as `memory/MEMORY.md.prev`),
`rejected` (bad line format, over `memory.max_bytes` / `memory.max_lines`, a
secret, or an output that would erase every entry -- MEMORY.md is untouched and the
summaries stay pending) or `unchanged`. `dropped_unused` lists entries that aged out;
`dropped_unsupported` lists lines that stated a result as proved / verified without
naming a claim whose current status is `verified` / `formally_verified` (or a
`COUNTEREXAMPLE_VERIFIED` / `FORMAL_PROOF_VERIFIED` dossier claim) -- memory never
upgrades evidence into proof.

The agent cites what it used in a `<memory_citations>` block (`ID | why`) at the end
of its final answer; the loop strips the block from the visible answer. Usage is
recorded once per `(entry, session)`: `CitationRecord` for a cited id that was shown,
`ExposureRecord` for every id shown. Retention follows: an entry cited by some session
ages from its last citation, one shown but never cited from when it was first shown,
and one never shown is kept. Typed-ledger entries are ranked the same way for the
context (`memory.ledger_entries`), except that failed attempts are always eligible.
See [memory.md](memory.md) and [skills.md](skills.md).

