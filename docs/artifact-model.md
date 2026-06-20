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
