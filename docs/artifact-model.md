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
  memory/                # structured memory (facts, decisions, hypotheses, …)
  claims.jsonl           # Claim
  evidence.jsonl         # EvidenceEntry (contradictions preserved)
  graph.jsonl            # GraphEdge (typed relations)
  experiments/EXP-*/     # run.py, results/ (stdout, stderr, manifest.yaml), summary.md
  papers/PAPER-*/        # metadata + cached full text / notes
  datasets/DATASET-*/    # metadata: hash, license, source
  repos/REPO-*/          # metadata (pinned commit, license, test outcome)
  problems/PROBLEM-*/     # math dossiers (statement, claims, report.md, …)
  proofs/PROOF-*/        # formal proof attempts (Lean/Coq/SMT)
  reviews/REVIEW-*/      # critic reviews and findings
  figures/FIGURE-*/      # reproducible figures (script, data hash, seed)
  drafts/                # LaTeX/BibTeX paper drafts
  index/                 # hybrid BM25 + embedding index
  journal/               # research-loop journal entries
  research/              # research-loop checkpoints/state
  usage/ledger.jsonl     # estimated token/cost ledger (UsageRecord)
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
| Patch | `PATCH-` | A proposed edit (applyable / revertable). |
| Review | `REVIEW-` | A critic review with structured findings. |
| Figure | `FIGURE-` | A regenerable plot with provenance. |

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

## Experiment-citation integrity

An experiment citation must point at a real `EXP-*` manifest: citing an id that
was never created is rejected, and citing a real but not-yet-run experiment is
recorded with an advisory (its results do not exist yet). Both the dossier and the
workspace-global evidence paths enforce this, mirroring the `PAPER-*` citation
grounding.
