# Roadmap

OpenTorus was developed incrementally across **Milestones 0–75**. The first
public release, **v0.0.3**, bundles that work into one coherent agent and starts
the versioned history fresh. The milestones group into three capability bands,
all present in v0.0.3:

- **Core (M0–M22)** — the inspectable, local-first foundation: workspace, memory,
  the permission policy, tools, claims/evidence/experiments, the agent loop,
  providers, and review mode.
- **Engineering loop (M23–M41)** — agentic write/patch tools, plan execution,
  retrieval and context selection, streaming, the cost ledger, the Rich TUI,
  evaluation/regression harnesses, and reproducibility replay.
- **Research agent (M42–M75)** — literature connectors and legal full-text
  acquisition, paper understanding and the hybrid index, knowledge synthesis,
  math/proof backends, the autonomous research and `prove` loops, pluggable and
  HPC execution, adversarial review, rigorous numerics, authoring/dissemination,
  datasets and code-as-evidence, the cross-workspace knowledge base, the
  read-only dashboard, and governance (DLP, budgets, model routing).

The flagship surface is the **credible math dossier** (`opentorus problem …` and
`opentorus prove`): one open problem, an auditable artifact graph, and an honest
report that never upgrades evidence into proof. The live design notes are in
[design-problem-model.md](design-problem-model.md) and
[design-adversarial-verification.md](design-adversarial-verification.md).

Each milestone is a small, reviewable step: run the tests, show the diff,
summarize the changes, stop. Post-v0.0.3 work continues in that style.

## The next capability band: the campaign engine

The fourth band, landed on the `campaign-engine` branch and recorded in
[adr/0001-campaign-engine.md](adr/0001-campaign-engine.md), turns the three
mostly linear loops into a **persistent, portfolio-based campaign engine**
(`opentorus campaign`): a typed append-only event log with a pure reducer,
branches with explicit root relations, a documented heuristic scheduler,
failed-attempt memory that gates retries, narrow worker roles in isolated
contexts, a semantic proof tree whose obligations close only against accepted
artifacts, theorem-level literature (`THMREF`, applicability checks, category
coverage), *actual* per-task model routing with an auditable ledger, a
`campaign` / `theorem` CLI, an optional read-only Textual dashboard, and a
build/wheel-install CI plus a non-publishing tag-triggered release workflow. It
does all of this without weakening any epistemic invariant, breaking `research`
or `prove`, re-recording golden transcripts, or rewriting existing dossiers.

What it deliberately does *not* do is decide mathematics: a campaign can finish
without solving the problem, and the problem's status stays derived from
dossier artifacts. Open ends this band leaves for later, in the same
milestone style: real parallel workers (`max_parallel_workers` is capped to 1
today), an LLM-driven de-duplication and scheduling advisor behind the reserved
task classes, and a migration of `prove` / `research` callers from the
`AgentLoop` compatibility facade to the control-plane policy objects directly.
See [campaign-engine.md](campaign-engine.md) for the workflow and
[model-routing.md](model-routing.md) for routing.
